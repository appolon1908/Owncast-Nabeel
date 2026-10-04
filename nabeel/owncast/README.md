# NABEEL Station — private Owncast test deployment

This compose overlay builds the checked-out Owncast source and binds both viewer/admin HTTP and RTMP ingest to loopback by default.

It is intentionally unsuitable for public production exposure until TLS, authentication, storage, backup, and edge policy are separately certified.

Start a private test with:

```bash
docker compose -f nabeel/owncast/compose.yaml up --build
```

Then configure the Owncast admin password interactively and send a test stream to the local RTMP endpoint. Never commit the stream key or admin password.
