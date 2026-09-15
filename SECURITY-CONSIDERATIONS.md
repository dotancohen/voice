# Security considerations

What protects the notes and recordings on their way between devices, and what
the person who runs a sync server has to do. The rules themselves are in
`../SYNC_SPECIFICATION.md` (AUTH-7, LISTEN-3, DISC-1).

## Contents

- [The connection is encrypted by default](#the-connection-is-encrypted-by-default)
- [Who may connect](#who-may-connect)
- [A reverse proxy in front of the listener](#a-reverse-proxy-in-front-of-the-listener)
- [Firewall](#firewall)
- [What travels through the listener](#what-travels-through-the-listener)
- [Secrets on disk](#secrets-on-disk)
- [The bucket](#the-bucket)

## The connection is encrypted by default

- `sync serve` (and File → Listen for devices in the GUI) serves **HTTPS** with
  the machine's own self-signed certificate, `<root>/certs/server.crt` with its
  key `<root>/certs/server.key` (mode 0600). Both are made at the first start
  of the listener.
- A caller verifies a device's certificate in one of two ways, and verification
  is never switched off:
  - a device with a pinned fingerprint is checked against that fingerprint only;
  - a device without one is checked against the system's root certificates, so a
    self-signed listener is refused.
- **There is no trust on first use.** A fingerprint is pinned by pairing
  (`account join`, `account grant-host`: the setup text carries it as `f=`), by
  `sync add-device --fingerprint`, or by LAN discovery. A wrong certificate is
  refused with `CERTIFICATE_MISMATCH`.
- A setup text shown by `account show-code` on an **indexed root** (a root with
  `accounts.db`) currently carries no `f=`: the code looks for the certificate
  in the account's directory instead of the root. Joining that listener over
  HTTPS then fails certificate verification. This is a defect, not a design.
- A caller refuses `http://` to any host other than `localhost`, `127.*` or
  `::1`: `… is plain http; a device key must not cross a network in clear
  (TLS_REQUIRED)`.
- The listener serves plain http only with `--plain-http`, and only on a
  loopback address. On any other address it refuses to start
  (`Plain http is allowed only on this machine itself, not on <host> (TLS_REQUIRED)`).

## Who may connect

- Every request except `GET /sync/status`, `POST /pair/claim` and
  `POST /pair/grant` carries the account id, the device id and the device's
  key. The listener refuses a device it does not know (`DEVICE_UNKNOWN`), a
  wrong key (`KEY_WRONG`), a missing key (`KEY_MISSING`), an account it does
  not serve (`ACCOUNT_UNKNOWN`) and a revoked device (`DEVICE_REVOKED`).
- Adding a device by hand does not let a device in: only pairing gives a device a
  key. `device revoke <id>` shuts a device out on every device that has received
  the revocation.
- A setup text is valid for ten minutes and one use; five wrong tokens withdraw
  it. After three refusals from one address, each further refusal is answered
  after 2, then 4, then 8 seconds.
- **The listener serves its own network only.** A caller whose address is not
  private (RFC 1918, `fc00::/7`), link-local or loopback is refused with
  `This device serves its own network only; it has no public address (NOT_ON_LAN)`,
  unless `public_url` is set in `<root>/config.json`. There is no command for
  `public_url`; edit the file. When it is set, callers from every address are
  served.

## A reverse proxy in front of the listener

Without `--plain-http` the listener speaks HTTPS, so an nginx
`proxy_pass http://…` to it fails. Start it on the loopback address with plain
http:

```bash
python -m src.main cli sync serve --host 127.0.0.1 --port 8384 --plain-http
```

```nginx
server {
    listen 443 ssl;
    server_name sync.example.com;
    # ssl_certificate and ssl_certificate_key: a certificate the devices'
    # system root certificates trust

    # Recordings stream through the listener; nginx refuses bodies over 1 MB by default
    client_max_body_size 0;

    location / {
        allow 192.168.1.0/24;
        allow 203.0.113.50;
        deny all;
        proxy_pass http://127.0.0.1:8384;
    }
}
```

Consequences:

- Every caller reaches the listener from 127.0.0.1, so the listener's own
  network check lets every caller through. The `allow` and `deny` lines in
  nginx are then the only restriction by address.
- The devices verify the proxy's certificate, not the listener's. They verify
  it against the system's root certificates only when their pairing text
  carried no fingerprint. `account host` puts the fingerprint of
  `<root>/certs/server.crt` into the grant text whenever that file exists (it
  exists after any start of `sync serve` without `--plain-http`); a holder that
  pinned it then refuses the proxy's certificate with `CERTIFICATE_MISMATCH`.
- Give the proxy's address to the offer: `account host --url https://sync.example.com`.
- With `--plain-http` the listener announces nothing on the local network.

## Firewall

Block all incoming traffic except SSH and the port that devices connect to:
443 for a reverse proxy, or the listener's port (`sync.server_port`, default
8384) when devices connect to the listener directly.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 443/tcp        # a reverse proxy; or: sudo ufw allow 8384/tcp
sudo ufw enable
```

## What travels through the listener

- Notes, tags, transcriptions, device cards and synced settings, as JSON. The
  JSON routes accept bodies up to `sync.max_sync_file_size_mb` (default 100 MB).
- **Recordings of any size**, streamed by `sync deliver`, `exchange`, `send`
  and `fetch`. They are not limited by `sync.max_sync_file_size_mb`.
- The listener of an indexed root writes one line per authenticated request to
  `<root>/<account id>/audit.log`. `/pair/*` and `/sync/status` are not
  logged; a single-directory listener writes no audit log.

## Secrets on disk

- `<root>/<account id>/config.json` (or `<dir>/config.json` in a one-account
  directory) holds this device's key (`sync.device_key`) and the account's
  recording key (`sync.recording_key`) **in clear** on the desktop. Only the
  phone wraps them with its key store.
- `<root>/accounts.db` has mode 0600, and so has `<root>/certs/server.key`.
- The bucket's access key and secret are kept in `notes.db` and are copied to
  every device of the account by sync. A revoked device still holds them:
  replace the key (`storage replace-key`) when that matters.
- Granting a group read access to the whole root (for example with
  `chmod -R g+rw`) gives that group the device keys and the certificate's
  private key.

## The bucket

- The bucket holds recordings only; notes, tags and transcriptions never go
  through it.
- The key that the wizard asks for may touch buckets named `voice-*` only. Its
  policy allows deleting an object (never a bucket); the application never
  assumes it may, and `../HARDENING-AGAINST-FAILURE-AND-ATTACKS.md` says how to
  take the permission away.
- Recordings are uploaded in clear unless encryption is on:
  `storage encrypt on`, allowed only after the recording key was exported
  (`account recording-key export`). An encrypted object is named
  `<sha256>.<ext>.enc`.
