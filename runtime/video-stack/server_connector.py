#!/usr/bin/env python3
"""Codestra server-side connector for canonical desktop Owncast."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

DESKTOP_BRIDGE=os.environ.get("CODESTRA_OWNCAST_DESKTOP_BRIDGE","http://10.0.0.73:18180").rstrip("/")
BRIDGE_TOKEN=os.environ.get("CODESTRA_OWNCAST_BRIDGE_TOKEN","")
LOCAL_TOKEN=os.environ.get("CODESTRA_VIDEO_API_TOKEN","")
WEBHOOK_SECRET=os.environ.get("OWNCAST_WEBHOOK_SECRET","")
WEBHOOK_SOURCE=os.environ.get("OWNCAST_WEBHOOK_SOURCE","10.0.0.73")
EVENT_LOG=Path(os.environ.get("OWNCAST_EVENT_LOG","/srv/codestra-video/events/owncast.jsonl"))
MAX_BODY=1024*1024
MAX_AGE_SECONDS=300

PROXY_ROUTES={
    ("GET","/v1/status"),
    ("GET","/v1/chat"),
    ("GET","/v1/clients"),
    ("POST","/v1/chat/system"),
    ("POST","/v1/chat/send"),
    ("POST","/v1/chat/action"),
    ("POST","/v1/chat/messagevisibility"),
    ("POST","/v1/stream/title"),
}
WEBHOOK_EVENTS={
    "CHAT","NAME_CHANGE","USER_JOINED","USER_PARTED","STREAM_STARTED","STREAM_STOPPED",
    "STREAM_TITLE_UPDATED","VISIBILITY-UPDATE","FEDIVERSE_ENGAGEMENT_FOLLOW"
}

def proxy(method,path,payload=None):
    headers={"Accept":"application/json","Authorization":"Bearer "+BRIDGE_TOKEN}
    if payload is not None:
        headers["Content-Type"]="application/json"
    req=Request(DESKTOP_BRIDGE+path,data=payload,headers=headers,method=method)
    try:
        with urlopen(req,timeout=5) as r:
            return r.status,r.read(MAX_BODY),r.headers.get("Content-Type","application/json")
    except HTTPError as e:
        return e.code,e.read(MAX_BODY),e.headers.get("Content-Type","text/plain")
    except (URLError,OSError,TimeoutError):
        return 503,b'{"error":"desktop_bridge_unreachable"}',"application/json"

def verify_owncast_signature(header,raw):
    if not WEBHOOK_SECRET or not header:
        return False
    parts={}
    for item in header.split(","):
        if "=" in item:
            k,v=item.split("=",1)
            parts[k.strip()]=v.strip()
    try:
        timestamp=int(parts["t"])
        signature=parts["s"]
    except (KeyError,ValueError):
        return False
    if abs(time.time()-timestamp)>MAX_AGE_SECONDS:
        return False
    expected=hmac.new(
        WEBHOOK_SECRET.encode(),
        str(timestamp).encode()+b"."+raw,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature,expected)

def append_event(payload):
    EVENT_LOG.parent.mkdir(parents=True,exist_ok=True)
    record={
        "received_at":time.time(),
        "type":payload.get("type"),
        "eventData":payload.get("eventData"),
    }
    with EVENT_LOG.open("a",encoding="utf-8") as f:
        f.write(json.dumps(record,separators=(",",":"),sort_keys=True)+"\n")

def recent_events(limit=50):
    if not EVENT_LOG.exists():
        return []
    lines=EVENT_LOG.read_text(encoding="utf-8",errors="replace").splitlines()[-max(1,min(limit,200)):]
    out=[]
    for line in lines:
        try: out.append(json.loads(line))
        except json.JSONDecodeError: pass
    return out

class LocalHandler(BaseHTTPRequestHandler):
    server_version="CodestraOwncastConnector/1.0"
    def log_message(self,*_): return
    def auth_ok(self):
        return bool(LOCAL_TOKEN) and self.headers.get("Authorization","")=="Bearer "+LOCAL_TOKEN
    def send_raw(self,status,body,ctype="application/json"):
        self.send_response(status); self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def body(self):
        n=int(self.headers.get("Content-Length","0"))
        if n<0 or n>MAX_BODY: raise ValueError("payload_too_large")
        raw=self.rfile.read(n)
        if raw:
            v=json.loads(raw)
            if not isinstance(v,dict): raise ValueError("json_object_required")
        return raw or b"{}"
    def dispatch(self,method):
        if not self.auth_ok():
            self.send_raw(401,b'{"error":"unauthorized"}'); return
        path=urlparse(self.path).path
        if path=="/health":
            code,body,_=proxy("GET","/health")
            try: upstream=json.loads(body)
            except Exception: upstream={}
            result={
                "status":"ok" if code==200 and upstream.get("status")=="ok" else "degraded",
                "service":"codestra-owncast-server-connector",
                "canonical_runtime":"codestra-desktop",
                "desktop_bridge_http_status":code,
                "desktop_bridge":upstream,
                "webhook_receiver_enabled":bool(WEBHOOK_SECRET),
            }
            self.send_raw(200,json.dumps(result,separators=(",",":")).encode()); return
        if path=="/v1/webhooks/recent" and method=="GET":
            self.send_raw(200,json.dumps({"events":recent_events()},separators=(",",":")).encode()); return
        if method=="GET" and path.startswith("/v1/users/"):
            code,body,ctype=proxy("GET","/v1/users/"+quote(path[len("/v1/users/"):],safe=""))
            self.send_raw(code,body,ctype); return
        if method=="POST" and path.startswith("/v1/chat/system/client/"):
            code,body,ctype=proxy("POST",path,self.body()); self.send_raw(code,body,ctype); return
        if (method,path) not in PROXY_ROUTES:
            self.send_raw(404,b'{"error":"not_found"}'); return
        code,body,ctype=proxy(method,path,self.body() if method=="POST" else None)
        self.send_raw(code,body,ctype)
    def do_GET(self):
        try:self.dispatch("GET")
        except (ValueError,json.JSONDecodeError) as e:self.send_raw(400,json.dumps({"error":str(e)}).encode())
    def do_POST(self):
        try:self.dispatch("POST")
        except (ValueError,json.JSONDecodeError) as e:self.send_raw(400,json.dumps({"error":str(e)}).encode())

class WebhookHandler(BaseHTTPRequestHandler):
    server_version="CodestraOwncastWebhook/1.0"
    def log_message(self,*_): return
    def send_json(self,status,obj):
        raw=json.dumps(obj,separators=(",",":")).encode()
        self.send_response(status); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if self.client_address[0]!=WEBHOOK_SOURCE:
            self.send_json(403,{"error":"source_not_allowed"}); return
        if urlparse(self.path).path!="/v1/webhooks/owncast":
            self.send_json(404,{"error":"not_found"}); return
        n=int(self.headers.get("Content-Length","0"))
        if n<0 or n>MAX_BODY:
            self.send_json(413,{"error":"payload_too_large"}); return
        raw=self.rfile.read(n)
        if not verify_owncast_signature(self.headers.get("owncast-signature",""),raw):
            self.send_json(401,{"error":"invalid_webhook_signature"}); return
        try: payload=json.loads(raw)
        except json.JSONDecodeError:
            self.send_json(400,{"error":"invalid_json"}); return
        event_type=payload.get("type")
        if event_type not in WEBHOOK_EVENTS:
            self.send_json(422,{"error":"unsupported_event_type"}); return
        append_event(payload)
        self.send_json(202,{"accepted":True,"type":event_type})

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--local-host",default="127.0.0.1")
    p.add_argument("--local-port",type=int,default=18104)
    p.add_argument("--webhook-host",default="10.0.0.220")
    p.add_argument("--webhook-port",type=int,default=18184)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        assert "STREAM_STARTED" in WEBHOOK_EVENTS
        assert ("POST","/v1/stream/title") in PROXY_ROUTES
        print(json.dumps({"ok":True,"service":"codestra-owncast-server-connector"})); return
    if not BRIDGE_TOKEN: raise SystemExit("CODESTRA_OWNCAST_BRIDGE_TOKEN_required")
    if not LOCAL_TOKEN: raise SystemExit("CODESTRA_VIDEO_API_TOKEN_required")
    if not WEBHOOK_SECRET: raise SystemExit("OWNCAST_WEBHOOK_SECRET_required")
    local=ThreadingHTTPServer((a.local_host,a.local_port),LocalHandler)
    webhook=ThreadingHTTPServer((a.webhook_host,a.webhook_port),WebhookHandler)
    threading.Thread(target=webhook.serve_forever,daemon=True).start()
    local.serve_forever()

if __name__=="__main__":
    main()
