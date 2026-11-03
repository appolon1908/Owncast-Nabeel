# Codestra Owncast canonical desktop bridge

The **only** authoritative Owncast runtime is the existing instance on
`codestra-desktop`. The middleware server must not host a second Owncast.

## Canonical topology

```
Codestra Video Controller 127.0.0.1:18100
        |
        | Owncast integration API
        v
Desktop API gateway 10.0.0.73:18181
        |
        v
Owncast 127.0.0.1:18080

Owncast signed webhooks
        |
        v
http://10.0.0.220:18110/webhooks/owncast
        |
        v
verified event journal + controller readback
```

The API gateway is restricted to the middleware server IP
`10.0.0.220/32`. Owncast itself remains loopback-only.

## Owncast API endpoints exposed through the private gateway

### GET

- `/api/integrations/status`
- `/api/integrations/chat`
- `/api/integrations/clients`
- `/api/integrations/moderation/chat/user/{userId}`

### POST

- `/api/integrations/streamtitle`
- `/api/integrations/chat/system`
- `/api/integrations/chat/send`
- `/api/integrations/chat/action`
- `/api/integrations/chat/messagevisibility`
- `/api/integrations/chat/system/client/{clientId}`

No `/api/admin/*` endpoint is proxied.

## Codestra Video Controller endpoints

### GET

- `/v1/owncast/status`
- `/v1/owncast/chat`
- `/v1/owncast/clients`
- `/v1/owncast/users/{userId}`
- `/v1/owncast/webhook-events?limit=25`

### POST

- `/v1/owncast/stream-title`
- `/v1/owncast/chat/system`
- `/v1/owncast/chat/send`
- `/v1/owncast/chat/action`
- `/v1/owncast/chat/message-visibility`
- `/v1/owncast/chat/system/client/{clientId}`

## Webhook events

All Owncast 0.3.0 documented webhook event types are accepted:

- `CHAT`
- `NAME_CHANGE`
- `USER_JOINED`
- `USER_PARTED`
- `STREAM_STARTED`
- `STREAM_STOPPED`
- `STREAM_TITLE_UPDATED`
- `VISIBILITY-UPDATE`
- `FEDIVERSE_ENGAGEMENT_FOLLOW`

The receiver validates `owncast-signature` using HMAC-SHA256 over the exact raw
body and rejects timestamps outside the documented five-minute replay window.

See `ACTIVATION.md` for installation and supported Owncast admin-API activation.
