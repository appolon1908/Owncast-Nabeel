# Video stack Owncast bridge

Owncast keeps its native Web APIs and scoped Access Tokens.

Staging runtime:

- Web/Admin: `http://127.0.0.1:18080`
- RTMP ingest: `127.0.0.1:19351`
- Admin/integration API mutations require an Owncast Access Token.
- No token is committed to this repository.
- The systemd network policy is loopback-only, so this instance cannot publish publicly during validation.

Access tokens are created through Owncast's admin access-token workflow and passed to the controller through the governed secret store.
