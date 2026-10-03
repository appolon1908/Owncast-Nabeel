# Codestra Owncast desktop authority and video-stack bridge

The **canonical Owncast runtime is the existing `nabeel-owncast` container on `codestra-desktop`**, not the middleware server.

Current local authority:
- Owncast web/API: `127.0.0.1:8081`
- Owncast RTMP: `127.0.0.1:1936`
- Private Codestra API gateway: `10.0.0.73:18181`, source-restricted to the middleware server
- Signed webhook receiver: `http://10.0.0.220:18110/webhooks/owncast`

## API coverage

The gateway allowlists every supported Owncast integration API in the current stable API:
- status
- chat history
- connected clients
- chat user details
- stream title updates
- system chat messages
- standard chat messages
- chat actions
- message visibility
- per-client system messages

The gateway does not proxy `/api/admin/*` and never exposes the Owncast admin password. It owns one scoped Owncast integration token and replaces the server-side bridge credential with the Owncast token only when forwarding an allowlisted request.

## Webhooks

The receiver supports all Owncast 0.3.0 webhook event types:
`CHAT`, `NAME_CHANGE`, `USER_JOINED`, `USER_PARTED`, `STREAM_STARTED`, `STREAM_STOPPED`, `STREAM_TITLE_UPDATED`, `VISIBILITY-UPDATE`, and `FEDIVERSE_ENGAGEMENT_FOLLOW`.

Every delivery must pass Owncast's `owncast-signature` HMAC-SHA256 verification and the five-minute replay window. Accepted events are appended to `/srv/codestra-video/events/owncast/events.jsonl`.

## Safety

- Desktop Owncast itself stays loopback-only.
- The private gateway accepts only the middleware server IP and a separate bridge bearer token.
- The webhook listener accepts only the desktop IP and signed Owncast webhook requests.
- Public streaming/social publishing remains separately gated.
- Middleware V3 remains the durable cross-system command, idempotency, audit, and reconciliation authority.
