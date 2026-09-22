# qshare

Quickly share a local file via a public TryCloudflare tunnel.

## Features

- Start a temporary local HTTP server on a random free port
- Detect and avoid occupied ports automatically
- Create a public TryCloudflare URL for the file
- Support a default lifetime of 30 minutes, adjustable via CLI arguments
- Ready for uv-managed development and PyPI packaging

## Requirements

`cloudflared` does not ship as an official Python package on PyPI. Instead, qshare will automatically download the official Cloudflare tunnel binary when it is missing.

If your network is limited or you want to use a mirror, set the environment variable before running qshare:

```bash
export CLOUDFLARED_DOWNLOAD_URL="https://example.com/mirror/cloudflared-linux-amd64"
```

If you want to install it manually for any reason, use:

- https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

## Install

Using uv:

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

Or install from PyPI after publishing:

```bash
pip install qshare
```

## Usage

```bash
qshare /path/to/file.zip
qshare /path/to/file.zip --ttl 2h
qshare /path/to/file.zip --ttl 900
qshare /path/to/file.zip --port 8000
```

The command starts a local HTTP server on a random free port, creates a temporary public URL with TryCloudflare, and keeps the tunnel alive for the configured duration. If `cloudflared` is absent, qshare will fetch the official binary automatically into `~/.local/bin`.

## Build for PyPI

```bash
uv build
```

Then upload the resulting artifacts from the `dist/` directory to PyPI.

## Notes

- The default lifetime is 30 minutes.
- If a port is occupied, qshare automatically selects another free port.
- `--ttl` accepts values like `30m`, `90s`, `2h`, or a plain number in seconds.
