#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hmac
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs

SECRET=os.environ.get("OWNCAST_WEBHOOK_SECRET","")
READ_TOKEN=os.environ.get("CODESTRA_VIDEO_API_TOKEN","")
ALLOWED_IPS={x.strip() for x in os.environ.get("OWNCAST_WEBHOOK_ALLOWED_IPS","10.0.0.73,127.0.0.1").split(",") if x.strip()}
EVENT_FILE=Path(os.environ.get("OWNCAST_WEBHOOK_EVENT_FILE","/srv/codestra-video/events/owncast/events.jsonl"))
MAX_BODY=1024*1024
EVENTS={
 "CHAT","NAME_CHANGE","USER_JOINED","USER_PARTED","STREAM_STARTED","STREAM_STOPPED",
 "STREAM_TITLE_UPDATED","VISIBILITY-UPDATE","FEDIVERSE_ENGAGEMENT_FOLLOW",
}
_lock=threading.Lock()

def verify(raw:bytes,header:str)->tuple[bool,str]:
    parts={}
    for part in (header or "").split("."):
        if "=" in part:
            k,v=part.strip().split("=",1); parts[k]=v
    ts=parts.get("t",""); sig=parts.get("s","")
    if not ts or not sig: return False,"signature_missing"
    try: stamp=int(ts)
    except ValueError: return False,"timestamp_invalid"
    if abs(int(time.time())-stamp)>300: return False,"signature_expired"
    expected=hmac.new(SECRET.encode(),ts.encode()+b"."+raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig,expected): return False,"signature_mismatch"
    return True,"ok"

def append_event(obj:dict,signature:str):
    EVENT_FILE.parent.mkdir(parents=True,exist_ok=True)
    record={"receivedAt":time.time(),"signature":signature,"type":obj["type"],"eventData":obj.get("eventData",{})}
    line=json.dumps(record,separators=(",",":"),sort_keys=True)+"\n"
    with _lock:
        with EVENT_FILE.open("a",encoding="utf-8") as f:
            f.write(line)
        os.chmod(EVENT_FILE,0o640)

def latest(limit:int):
    if not EVENT_FILE.exists(): return []
    limit=max(1,min(limit,100))
    with _lock:
        lines=EVENT_FILE.read_text(encoding="utf-8",errors="replace").splitlines()
    result=[]
    for line in lines[-limit:]:
        try: result.append(json.loads(line))
        except Exception: pass
    return result

class Handler(BaseHTTPRequestHandler):
    server_version="CodestraOwncastWebhook/1.0"
    def log_message(self,*_): return
    def source_ok(self): return self.client_address[0] in ALLOWED_IPS
    def sendj(self,status,obj):
        raw=json.dumps(obj,separators=(",",":"),sort_keys=True).encode()
        self.send_response(status); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store")
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        p=urlsplit(self.path)
        if p.path=="/health":
            self.sendj(200,{"status":"ok","service":"codestra-owncast-webhook","event_types":sorted(EVENTS)})
            return
        if p.path=="/events":
            if not READ_TOKEN or self.headers.get("Authorization","")!=f"Bearer {READ_TOKEN}":
                self.sendj(401,{"error":"unauthorized"}); return
            q=parse_qs(p.query); limit=int(q.get("limit",["25"])[0])
            self.sendj(200,{"events":latest(limit)}); return
        self.sendj(404,{"error":"not_found"})
    def do_POST(self):
        p=urlsplit(self.path)
        if p.path!="/webhooks/owncast":
            self.sendj(404,{"error":"not_found"}); return
        if not self.source_ok():
            self.sendj(403,{"error":"source_not_allowed"}); return
        n=int(self.headers.get("Content-Length","0"))
        if n<0 or n>MAX_BODY:
            self.sendj(413,{"error":"payload_too_large"}); return
        raw=self.rfile.read(n)
        ok,reason=verify(raw,self.headers.get("owncast-signature",""))
        if not ok:
            self.sendj(401,{"error":reason}); return
        try:
            obj=json.loads(raw)
        except Exception:
            self.sendj(400,{"error":"invalid_json"}); return
        event_type=obj.get("type")
        if event_type not in EVENTS or not isinstance(obj.get("eventData",{}),dict):
            self.sendj(400,{"error":"unsupported_event"}); return
        append_event(obj,self.headers.get("owncast-signature",""))
        self.sendj(202,{"accepted":True,"type":event_type})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--host",default="10.0.0.220")
    ap.add_argument("--port",type=int,default=18110)
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:
        global SECRET
        SECRET="test-secret"
        body=b'{"type":"STREAM_STARTED","eventData":{}}'
        ts=str(int(time.time()))
        sig=hmac.new(SECRET.encode(),ts.encode()+b"."+body,hashlib.sha256).hexdigest()
        assert verify(body,f"t={ts}.s={sig}")[0]
        assert not verify(body,f"t={ts}.s={'0'*64}")[0]
        print(json.dumps({"ok":True,"service":"codestra-owncast-webhook"}))
        return
    if not SECRET:
        raise SystemExit("OWNCAST_WEBHOOK_SECRET_required")
    ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()

if __name__=="__main__":
    main()
