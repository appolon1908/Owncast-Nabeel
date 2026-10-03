#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BASE=os.environ.get("OWNCAST_BASE_URL","http://127.0.0.1:8081").rstrip("/")
OWNCAST_TOKEN=os.environ.get("OWNCAST_ACCESS_TOKEN","")
BRIDGE_TOKEN=os.environ.get("CODESTRA_OWNCAST_BRIDGE_TOKEN","")  # optional; source-IP restriction is mandatory
ALLOWED_IPS={x.strip() for x in os.environ.get("CODESTRA_OWNCAST_ALLOWED_IPS","10.0.0.220,127.0.0.1").split(",") if x.strip()}
MAX_BODY=1024*1024

GET_EXACT={
    "/api/integrations/status",
    "/api/integrations/chat",
    "/api/integrations/clients",
}
POST_EXACT={
    "/api/integrations/chat/system",
    "/api/integrations/chat/send",
    "/api/integrations/chat/action",
    "/api/integrations/chat/messagevisibility",
    "/api/integrations/streamtitle",
}
USER_RE=re.compile(r"^/api/integrations/moderation/chat/user/[A-Za-z0-9_-]+$")
CLIENT_RE=re.compile(r"^/api/integrations/chat/system/client/[0-9]+$")

def allowed(method:str,path:str)->bool:
    if method=="GET":
        return path in GET_EXACT or bool(USER_RE.fullmatch(path))
    if method=="POST":
        return path in POST_EXACT or bool(CLIENT_RE.fullmatch(path))
    return False

def upstream(method:str,path_and_query:str,body:bytes|None):
    if not OWNCAST_TOKEN:
        return 503,"application/json",b'{"error":"owncast_access_token_not_configured"}'
    headers={"Authorization":f"Bearer {OWNCAST_TOKEN}","Accept":"application/json"}
    if body is not None:
        headers["Content-Type"]="application/json"
    req=Request(BASE+path_and_query,data=body,headers=headers,method=method)
    try:
        with urlopen(req,timeout=5) as r:
            return r.status,r.headers.get("Content-Type","application/json"),r.read(MAX_BODY)
    except HTTPError as e:
        return e.code,e.headers.get("Content-Type","text/plain"),e.read(MAX_BODY)
    except (URLError,TimeoutError,OSError):
        return 503,"application/json",b'{"error":"owncast_unreachable"}'

class Handler(BaseHTTPRequestHandler):
    server_version="CodestraOwncastGateway/1.0"
    def log_message(self,*_): return

    def source_ok(self):
        return self.client_address[0] in ALLOWED_IPS

    def auth_ok(self):
        return (not BRIDGE_TOKEN) or self.headers.get("Authorization","")==f"Bearer {BRIDGE_TOKEN}"

    def send_bytes(self,status,ctype,data):
        self.send_response(status)
        self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self,status,obj):
        self.send_bytes(status,"application/json",json.dumps(obj,separators=(",",":"),sort_keys=True).encode())

    def check(self):
        if not self.source_ok():
            self.send_json(403,{"error":"source_not_allowed"})
            return False
        if not self.auth_ok():
            self.send_json(401,{"error":"unauthorized"})
            return False
        return True

    def do_GET(self):
        p=urlsplit(self.path)
        if not self.check(): return
        if p.path=="/health":
            try:
                req=Request(BASE+"/api/status",headers={"Accept":"application/json"},method="GET")
                with urlopen(req,timeout=3) as r:
                    public_status=r.status
                    public_body=json.loads(r.read(MAX_BODY) or b"{}")
            except Exception:
                public_status=503
                public_body={}
            self.send_json(200 if public_status==200 else 503,{
                "status":"ok" if public_status==200 else "degraded",
                "service":"codestra-owncast-gateway",
                "owncast_status":public_status,
                "owncast_version":public_body.get("versionNumber"),
                "integration_ready":bool(OWNCAST_TOKEN),
            })
            return
        if not allowed("GET",p.path):
            self.send_json(404,{"error":"route_not_allowed"}); return
        suffix=p.path+("?" + p.query if p.query else "")
        st,ctype,data=upstream("GET",suffix,None)
        self.send_bytes(st,ctype,data)

    def do_POST(self):
        p=urlsplit(self.path)
        if not self.check(): return
        if not allowed("POST",p.path):
            self.send_json(404,{"error":"route_not_allowed"}); return
        n=int(self.headers.get("Content-Length","0"))
        if n<0 or n>MAX_BODY:
            self.send_json(413,{"error":"payload_too_large"}); return
        body=self.rfile.read(n)
        if body:
            try:
                value=json.loads(body)
                if not isinstance(value,dict): raise ValueError
            except Exception:
                self.send_json(400,{"error":"json_object_required"}); return
        else:
            body=b"{}"
        st,ctype,data=upstream("POST",p.path,body)
        self.send_bytes(st,ctype,data)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--host",default="10.0.0.73")
    ap.add_argument("--port",type=int,default=18181)
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:
        assert allowed("GET","/api/integrations/status")
        assert allowed("GET","/api/integrations/moderation/chat/user/abc_123")
        assert allowed("POST","/api/integrations/chat/system/client/42")
        assert not allowed("POST","/api/admin/accesstokens/create")
        print(json.dumps({"ok":True,"service":"codestra-owncast-gateway"}))
        return
    if not OWNCAST_TOKEN or not BRIDGE_TOKEN:
        raise SystemExit("required_credentials_missing")
    ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()

if __name__=="__main__":
    main()
