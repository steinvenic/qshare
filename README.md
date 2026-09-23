# qshare

Quickly share a local file via a public TryCloudflare tunnel.

## Features

- Start a temporary local HTTP server on a random free port
- Detect and avoid occupied ports automatically
- Create a public TryCloudflare URL for the file
- Support a default lifetime of 2 hours, adjustable via CLI arguments
- Works on Linux and Windows, with automatic cloudflared download support
- Ready for uv-managed development and PyPI packaging

## Requirements

- Python 3.6+
- `cloudflared` does not ship as an official Python package on PyPI. Instead, qshare will automatically download the official Cloudflare tunnel binary when it is missing.

qshare supports both Linux and Windows; the installer selects the matching official Cloudflare binary automatically.

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

The command starts a local HTTP server on a random free port, creates a temporary public URL with TryCloudflare, and keeps the tunnel alive for the configured duration. If `cloudflared` is absent, qshare will fetch the official binary automatically into `~/.local/bin`. Automatic installation supports Cloudflare's current Linux (x86, x86_64, ARM, ARMHF, ARM64), Windows (x86, x86_64), and macOS (Intel, Apple Silicon) binary releases.

After the public URL is printed prominently, qshare prompts on Unix-like systems: `Run in background? Press 'd' to detach, or press Enter to keep in the foreground.` Windows always runs in the foreground. When the TTL expires in foreground mode, qshare prints a notification and stops the share.

## Build for PyPI

```bash
uv build
```

Then upload the resulting artifacts from the `dist/` directory to PyPI.

## Notes

- The default lifetime is 2 hours.
- If a port is occupied, qshare automatically selects another free port.
- `--ttl` accepts values like `30m`, `90s`, `2h`, or a plain number in seconds.
- Background mode is triggered by entering `d` at the interactive prompt after the public URL appears.
