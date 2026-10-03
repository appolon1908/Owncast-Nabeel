# Owncast video-stack activation

The canonical Owncast runtime stays on `codestra-desktop`. The middleware server duplicate was removed on 2026-10-03; do not recreate it.

## Runtime addresses

- Owncast web/API: `http://127.0.0.1:18080`
- Owncast RTMP ingest: `rtmp://127.0.0.1:1936/live/<stream-key>`
- Codestra private gateway: `http://10.0.0.73:18181`
- Middleware signed webhook receiver: `http://10.0.0.220:18110/webhooks/owncast`

Owncast itself remains loopback-only. Only the narrow Codestra gateway is reachable from the middleware host, and its systemd IP policy only allows `10.0.0.220/32`.

## Recommended activation helper

After the bridge files are installed, run this interactively on `codestra-desktop`:

```bash
sudo /opt/codestra-video/owncast-gateway/activate_owncast_bridge.py
```

It prompts without echo for the Owncast admin password, the webhook secret from the middleware host, and the Codestra Owncast bridge token. It then uses only Owncast's supported admin API to create/reuse the scoped access token, registers all webhook events, writes the protected gateway environment file, restarts the gateway, and validates the integration. It never prints the credentials.

The middleware host stores two generated secrets locally: the Owncast webhook secret and the private desktop-bridge bearer token. Do not copy either into Git or chat. An authorized operator can read them locally only during activation.

Webhook secret:

```bash
sudo sed -n 's/^OWNCAST_WEBHOOK_SECRET=//p' /etc/codestra-video/owncast-webhook.env
```

Bridge token:

```bash
sudo cat /etc/codestra-video/.owncast-bridge-token
```

## 1. Create the supported Owncast integration token

On `codestra-desktop`, open:

`http://127.0.0.1:18080/admin/access-tokens`

Create an access token named **Codestra Video Controller** with:

- `CAN_SEND_MESSAGES`
- `CAN_SEND_SYSTEM_MESSAGES`
- `HAS_ADMIN_ACCESS`

Do not commit or paste this token into GitHub, chat, logs, or source code.

Store it locally:

```bash
sudo install -d -m 0750 -o root -g codestra /etc/codestra-video
sudoedit /etc/codestra-video/owncast-gateway.env
```

The file must contain:

```text
OWNCAST_BASE_URL=http://127.0.0.1:18080
OWNCAST_ACCESS_TOKEN=<OWNCAST ACCESS TOKEN>
CODESTRA_OWNCAST_BRIDGE_TOKEN=<CODESTRA BRIDGE TOKEN>\nCODESTRA_OWNCAST_ALLOWED_IPS=10.0.0.220,127.0.0.1
```

Then:

```bash
sudo chown root:codestra /etc/codestra-video/owncast-gateway.env
sudo chmod 0640 /etc/codestra-video/owncast-gateway.env
sudo systemctl enable --now codestra-owncast-api-gateway.service
```

## 2. Register every supported webhook event

On `codestra-desktop`, open:

`http://127.0.0.1:18080/admin/webhooks`

Create a webhook with URL:

`http://10.0.0.220:18110/webhooks/owncast`

Select every current Owncast 0.3.0 event:

- `CHAT`
- `NAME_CHANGE`
- `USER_JOINED`
- `USER_PARTED`
- `STREAM_STARTED`
- `STREAM_STOPPED`
- `STREAM_TITLE_UPDATED`
- `VISIBILITY-UPDATE`
- `FEDIVERSE_ENGAGEMENT_FOLLOW`

The webhook secret is generated/stored only on the middleware host at:

`/etc/codestra-video/owncast-webhook.env`

An authorized operator can display only the secret locally while configuring Owncast:

```bash
sudo sed -n 's/^OWNCAST_WEBHOOK_SECRET=//p' /etc/codestra-video/owncast-webhook.env
```

Do not copy the secret into the repository.

## 3. API surface

The private gateway exposes only the current supported Owncast integration API:

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

## 4. Codestra Video Controller surface

Middleware-local callers use:

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

Middleware V3 remains the durable command, authorization, idempotency, audit, and reconciliation authority for cross-system effects.

## 5. Validation

```bash
curl -fsS http://10.0.0.73:18181/health
curl -fsS http://10.0.0.220:18110/health
```

The desktop Owncast ports `8081` and `1936` must remain unavailable from the LAN. The old middleware-host Owncast ports `18080` and `19351` must remain unused.

## 6. Private media transport

Owncast's HTTP API does not carry the video stream itself. The canonical media path is:

```text
middleware / MediaMTX / FFmpeg
        -> 10.0.0.73:19361
        -> source-restricted desktop socat relay
        -> 127.0.0.1:1936
        -> canonical Owncast
```

The real Owncast RTMP listener remains loopback-only. Only `10.0.0.220/32` may reach a private relay. The relay must not be enabled until the desktop's actual loopback RTMP port is re-read after the current desktop reconnect; the previously drafted `1936` target is not treated as certified runtime truth.

The MediaMTX destination is `owncast-desktop` and remains disabled by default. Its stream key is supplied only through the environment variable:

`NABEEL_OWNCAST_STREAM_KEY`

Store that value on the middleware host in a protected runtime environment file; never commit it to Git. Enabling the destination remains a separate staging/production-effect decision.
