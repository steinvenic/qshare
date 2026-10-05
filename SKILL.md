---
name: qshare
description: Share one local file through a temporary TryCloudflare URL or, with explicit confirmation, upload it to the qshare CNB release.
metadata:
  openclaw:
    homepage: https://github.com/steinvenic/qshare
    requires:
      bins:
        - qshare
    install:
      - id: uv
        kind: uv
        package: qshare
        bins:
          - qshare
        label: Install qshare from PyPI (uv)
---

# qshare

Use this skill when the user asks to make a local file available through a public
download URL or QR code. qshare serves the selected file from the local machine
and, by default, exposes it through a temporary TryCloudflare tunnel; the file is
not stored on qshare's servers.

## Share through TryCloudflare

1. Resolve the exact local file path. If the user has not identified one file,
   ask for the path instead of sharing a directory or guessing a filename.
2. Tell the user that the resulting URL has no access control. Recommend
   encrypting private or sensitive files before sharing them.
3. Run qshare with the path quoted so spaces and shell metacharacters are safe:

   ```bash
   qshare "/path/to/file.zip"
   ```

   Pass `--ttl 30m`, `--ttl 90s`, `--ttl 2h`, or a positive number of seconds
   when the user requests a different lifetime. Pass `--port PORT` only when a
   fixed local port is needed; otherwise let qshare choose a free port.
4. Report the line labelled `PUBLIC FILE URL` exactly as printed. The URL stops
   working when its TTL expires or the process is stopped. A QR renderer failure
   does not invalidate a successfully printed URL.

Do not expose arbitrary local paths, directory listings, or additional files.
Do not claim that a TryCloudflare share is persistent or access-controlled.

## CNB upload

Use `--cnb` only when the user explicitly chooses the CNB channel and accepts
that the file will be stored in the CNB Release rather than served temporarily:

```bash
qshare "/path/to/file.zip" --cnb
```

Before starting, explain that this is an upload to CNB and obtain an explicit
yes/no confirmation. Never bypass qshare's confirmation prompt or silently
switch a normal share to CNB. Treat sensitive files as requiring encryption
before upload. Return the `PUBLIC FILE URL` printed after a successful upload;
the CNB release is not automatically deleted by qshare.

## Operational notes

- Keep the qshare process running for foreground shares; its local server and
  tunnel are part of the share lifecycle.
- On Unix-like systems qshare may offer to detach into the background. Only
  choose that mode when the user asks for background operation; Windows remains
  in the foreground.
- qshare installs or uses a matching `cloudflared` binary as documented by the
  package. Do not download an unrelated binary or weaken TryCloudflare URL
  validation to work around an error.
- If qshare reports an error, show the actionable error text and do not invent a
  URL. Never print credentials or tokens from the runtime environment.
