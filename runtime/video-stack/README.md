# Codestra Owncast canonical desktop bridge

The canonical Owncast runtime lives on **codestra-desktop** at `127.0.0.1:18080`.
There must not be a second authoritative Owncast runtime on the middleware server.

## Topology

```
Middleware / Video Controller
  -> server connector 127.0.0.1:18104
  -> authenticated LAN bridge 10.0.0.73:18180
  -> Owncast 127.0.0.1:18080

Owncast signed webhooks
  -> http://10.0.0.220:18184/v1/webhooks/owncast
  -> signature validation + replay window
  -> /srv/codestra-video/events/owncast.jsonl
```

The desktop bridge accepts only `10.0.0.220` plus loopback and requires
`CODESTRA_OWNCAST_BRIDGE_TOKEN`. The server webhook receiver accepts only
`10.0.0.73`, validates Owncast v0.3.0 `owncast-signature` HMAC-SHA256,
and rejects timestamps outside five minutes.

## Normalized API

Read endpoints:

- `GET /health`
- `GET /v1/status`
- `GET /v1/chat`
- `GET /v1/clients`
- `GET /v1/users/{userId}`
- `GET /v1/webhooks/recent`

Mutation endpoints (default-disabled on the desktop bridge):

- `POST /v1/chat/system`
- `POST /v1/chat/send`
- `POST /v1/chat/action`
- `POST /v1/chat/messagevisibility`
- `POST /v1/stream/title`
- `POST /v1/chat/system/client/{clientId}`

Native Owncast scopes remain authoritative:

- `CAN_SEND_MESSAGES`
- `CAN_SEND_SYSTEM_MESSAGES`
- `HAS_ADMIN_ACCESS`

## Webhook events

The receiver supports all documented Owncast webhook event types:

- `CHAT`
- `NAME_CHANGE`
- `USER_JOINED`
- `USER_PARTED`
- `STREAM_STARTED`
- `STREAM_STOPPED`
- `STREAM_TITLE_UPDATED`
- `VISIBILITY-UPDATE`
- `FEDIVERSE_ENGAGEMENT_FOLLOW`

No token or webhook secret is committed. Create the Owncast Access Token and
webhook secret in the Owncast admin integration screens, then place them in
the root-readable environment files on their respective hosts.
