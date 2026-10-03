#!/usr/bin/env python3
"""Codestra desktop bridge for the canonical Owncast runtime.

This service runs beside Owncast on codestra-desktop. It exposes a small,
authenticated LAN API to the middleware server and translates requests to
Owncast's official access-token integration API on localhost.
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

OWNCAST_URL = os.environ.get("OWNCAST_URL", "http://127.0.0.1:18080").rstrip("/")
OWNCAST_TOKEN = os.environ.get("OWNCAST_ACCESS_TOKEN", "")
BRIDGE_TOKEN = os.environ.get("CODESTRA_OWNCAST_BRIDGE_TOKEN", "")
ALLOWED_CLIENT = os.environ.get("CODESTRA_OWNCAST_ALLOWED_CLIENT", "10.0.0.220")
MUTATIONS_ENABLED = os.environ.get("CODESTRA_OWNCAST_MUTATIONS_ENABLED", "0").lower() in {"1","true","yes","on"}
MAX_BODY = 1024 * 1024

ROUTES = {
    ("GET", "/v1/status"): ("GET", "/api/integrations/status", "HAS_ADMIN_ACCESS", False),
    ("GET", "/v1/chat"): ("GET", "/api/integrations/chat", "HAS_ADMIN_ACCESS", False),
    ("GET", "/v1/clients"): ("GET", "/api/integrations/clients", "HAS_ADMIN_ACCESS", False),
    ("POST", "/v1/chat/system"): ("POST", "/api/integrations/chat/system", "CAN_SEND_SYSTEM_MESSAGES", True),
    ("POST", "/v1/chat/send"): ("POST", "/api/integrations/chat/send", "CAN_SEND_MESSAGES", True),
    ("POST", "/v1/chat/action"): ("POST", "/api/integrations/chat/action", "CAN_SEND_SYSTEM_MESSAGES", True),
    ("POST", "/v1/chat/messagevisibility"): ("POST", "/api/integrations/chat/messagevisibility", "HAS_ADMIN_ACCESS", True),
    ("POST", "/v1/stream/title"): ("POST", "/api/integrations/streamtitle", "HAS_ADMIN_ACCESS", True),
}

def native(method: str, path: str, payload: bytes | None = None):
    headers={"Accept":"application/json","Authorization":"Bearer "+OWNCAST_TOKEN}
    if payload is not None:
        headers["Content-Type"]="application/json"
    req=Request(OWNCAST_URL+path,data=payload,headers=headers,method=method)
    try:
        with urlopen(req,timeout=5) as r:
            raw=r.read(MAX_BODY)
            return r.status, raw, r.headers.get("Content-Type","application/json")
    except HTTPError as e:
        return e.code, e.read(MAX_BODY), e.headers.get("Content-Type","text/plain")
    except (URLError, OSError, TimeoutError):
        return 503, b'{"error":"owncast_unreachable"}', "application/json"

class Handler(BaseHTTPRequestHandler):
    server_version="CodestraOwncastDesktopBridge/1.0"

    def log_message(self, *_):
        return

    def client_ok(self):
        return self.client_address[0] in {ALLOWED_CLIENT, "127.0.0.1", "::1"}

    def auth_ok(self):
        return bool(BRIDGE_TOKEN) and self.headers.get("Authorization","") == "Bearer "+BRIDGE_TOKEN

    def send_raw(self,status,body,ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n=int(self.headers.get("Content-Length","0"))
        if n<0 or n>MAX_BODY:
            raise ValueError("payload_too_large")
        raw=self.rfile.read(n)
        if raw:
            value=json.loads(raw)
            if not isinstance(value,dict):
                raise ValueError("json_object_required")
        return raw or b"{}"

    def dispatch(self,method):
        if not self.client_ok():
            self.send_raw(403,b'{"error":"source_not_allowed"}')
            return
        if not self.auth_ok():
            self.send_raw(401,b'{"error":"unauthorized"}')
            return
        path=urlparse(self.path).path
        if path=="/health":
            code, body, _ = native("GET","/api/integrations/status")
            result={
                "status":"ok" if code==200 else "degraded",
                "service":"codestra-owncast-desktop-bridge",
                "owncast_reachable":code not in {502,503},
                "owncast_authenticated":code==200,
                "mutations_enabled":MUTATIONS_ENABLED,
                "canonical_runtime":"codestra-desktop",
            }
            self.send_raw(200,json.dumps(result,separators=(",",":")).encode())
            return

        if method=="GET" and path.startswith("/v1/users/"):
            user_id=quote(path[len("/v1/users/"):],safe="")
            code,body,ctype=native("GET","/api/integrations/moderation/chat/user/"+user_id)
            self.send_raw(code,body,ctype)
            return

        if method=="POST" and path.startswith("/v1/chat/system/client/"):
            if not MUTATIONS_ENABLED:
                self.send_raw(423,b'{"error":"owncast_mutations_disabled"}')
                return
            client_id=quote(path[len("/v1/chat/system/client/"):],safe="")
            code,body,ctype=native("POST","/api/integrations/chat/system/client/"+client_id,self.read_body())
            self.send_raw(code,body,ctype)
            return

        route=ROUTES.get((method,path))
        if not route:
            self.send_raw(404,b'{"error":"not_found"}')
            return
        native_method,native_path,_scope,is_mutation=route
        if is_mutation and not MUTATIONS_ENABLED:
            self.send_raw(423,b'{"error":"owncast_mutations_disabled"}')
            return
        payload=self.read_body() if method=="POST" else None
        code,body,ctype=native(native_method,native_path,payload)
        self.send_raw(code,body,ctype)

    def do_GET(self):
        try: self.dispatch("GET")
        except (ValueError,json.JSONDecodeError) as e:
            self.send_raw(400,json.dumps({"error":str(e)}).encode())

    def do_POST(self):
        try: self.dispatch("POST")
        except (ValueError,json.JSONDecodeError) as e:
            self.send_raw(400,json.dumps({"error":str(e)}).encode())

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--host",default="10.0.0.73")
    p.add_argument("--port",type=int,default=18180)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        assert ("GET","/v1/status") in ROUTES
        assert ("POST","/v1/stream/title") in ROUTES
        print(json.dumps({"ok":True,"service":"codestra-owncast-desktop-bridge"}))
        return
    if not OWNCAST_TOKEN:
        raise SystemExit("OWNCAST_ACCESS_TOKEN_required")
    if not BRIDGE_TOKEN:
        raise SystemExit("CODESTRA_OWNCAST_BRIDGE_TOKEN_required")
    ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()

if __name__=="__main__":
    main()
