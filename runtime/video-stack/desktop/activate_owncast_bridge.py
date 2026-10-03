#!/usr/bin/env python3
"""Activate the Codestra Owncast bridge using Owncast's supported admin APIs.

Run interactively as root on codestra-desktop. Secrets are read with getpass and
are never printed. This script does not modify Owncast's database directly.
"""
from __future__ import annotations

import base64
import getpass
import grp
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE="http://127.0.0.1:8081"
GATEWAY_ENV=Path("/etc/codestra-video/owncast-gateway.env")
WEBHOOK_URL="http://10.0.0.220:18110/webhooks/owncast"
NAME="Codestra Video Controller"
SCOPES=["CAN_SEND_SYSTEM_MESSAGES","CAN_SEND_MESSAGES","HAS_ADMIN_ACCESS"]
EVENTS=[
 "CHAT","NAME_CHANGE","USER_JOINED","USER_PARTED",
 "STREAM_STARTED","STREAM_STOPPED","STREAM_TITLE_UPDATED",
 "VISIBILITY-UPDATE","FEDIVERSE_ENGAGEMENT_FOLLOW",
]
CSRF="X-Owncast-CSRF-Protection"

def request(path:str,password:str,method:str="GET",payload:dict|None=None):
    auth=base64.b64encode(("admin:"+password).encode()).decode()
    body=None if payload is None else json.dumps(payload).encode()
    headers={"Authorization":"Basic "+auth,"Accept":"application/json",CSRF:"1"}
    if body is not None:
        headers["Content-Type"]="application/json"
    req=Request(BASE+path,data=body,headers=headers,method=method)
    try:
        with urlopen(req,timeout=5) as r:
            raw=r.read(1024*1024)
            return r.status,json.loads(raw or b"{}")
    except HTTPError as e:
        raw=e.read(1024*1024)
        try: detail=json.loads(raw or b"{}")
        except Exception: detail={"body":raw.decode(errors="replace")[:500]}
        raise RuntimeError(f"Owncast admin API returned HTTP {e.code}: {detail}") from None

def integration_request(token:str,path:str):
    req=Request(BASE+path,headers={"Authorization":"Bearer "+token,"Accept":"application/json"},method="GET")
    with urlopen(req,timeout=5) as r:
        return r.status,json.loads(r.read(1024*1024) or b"{}")

def main():
    if os.geteuid()!=0:
        raise SystemExit("run this activation helper with sudo")
    password=getpass.getpass("Owncast admin password: ")
    webhook_secret=getpass.getpass("Codestra webhook secret from middleware server: ")
    if not password or not webhook_secret:
        raise SystemExit("credentials must not be empty")

    _,tokens=request("/api/admin/accesstokens",password)
    matching=[x for x in tokens if x.get("displayName")==NAME]
    token=None
    for item in matching:
        if set(item.get("scopes") or [])==set(SCOPES) and item.get("accessToken"):
            token=item["accessToken"]
            break

    if token is None:
        _,created=request("/api/admin/accesstokens/create",password,"POST",{"name":NAME,"scopes":SCOPES})
        token=created.get("accessToken")
        if not token:
            raise RuntimeError("Owncast did not return a token")

    _,hooks=request("/api/admin/webhooks",password)
    for hook in hooks:
        if hook.get("url")==WEBHOOK_URL and hook.get("id") is not None:
            request("/api/admin/webhooks/delete",password,"POST",{"id":int(hook["id"])})

    _,created_hook=request("/api/admin/webhooks/create",password,"POST",{
        "url":WEBHOOK_URL,
        "events":EVENTS,
        "secret":webhook_secret,
    })
    if created_hook.get("url")!=WEBHOOK_URL:
        raise RuntimeError("webhook creation readback mismatch")

    GATEWAY_ENV.parent.mkdir(parents=True,exist_ok=True)
    GATEWAY_ENV.write_text(
        "OWNCAST_BASE_URL=http://127.0.0.1:8081\n"
        f"OWNCAST_ACCESS_TOKEN={token}\n"
        "CODESTRA_OWNCAST_ALLOWED_IPS=10.0.0.220,127.0.0.1\n",
        encoding="utf-8",
    )
    gid=grp.getgrnam("codestra").gr_gid
    os.chown(GATEWAY_ENV,0,gid)
    os.chmod(GATEWAY_ENV,0o640)

    subprocess.run(["systemctl","restart","codestra-owncast-api-gateway.service"],check=True)
    subprocess.run(["systemctl","is-active","--quiet","codestra-owncast-api-gateway.service"],check=True)

    status,body=integration_request(token,"/api/integrations/status")
    if status!=200 or "versionNumber" not in body:
        raise RuntimeError("Owncast integration status validation failed")

    print(json.dumps({
        "ok":True,
        "service":"codestra-owncast-api-gateway",
        "owncast_version":body.get("versionNumber"),
        "integration_ready":True,
        "scopes":len(SCOPES),
        "webhook_events":len(EVENTS),
        "webhook_url":WEBHOOK_URL,
    },sort_keys=True))

if __name__=="__main__":
    main()
