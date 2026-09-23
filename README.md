# qshare

Quickly share a local file via a public TryCloudflare tunnel.

## Features

- Start a temporary local HTTP server on a random free port
- Detect and avoid occupied ports automatically
- Create a public TryCloudflare URL for the file
- Support a default lifetime of 2 hours, adjustable via CLI arguments
- Works on Linux, Windows, and macOS with a platform-specific bundled cloudflared binary
- Ready for uv-managed development and PyPI packaging

## Requirements

- Python 3.6+
- qshare platform wheels include the matching official `cloudflared` binary. qshare never downloads a binary at runtime; update qshare from PyPI to receive an updated bundled binary.

On a platform without a matching wheel, install `cloudflared` manually and add it to `PATH`.

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

The command starts a local HTTP server on a random free port, creates a temporary public URL with TryCloudflare, and keeps the tunnel alive for the configured duration. If `cloudflared` is absent from `PATH`, qshare installs the binary bundled in the matching PyPI wheel into `~/.local/bin`. Platform wheels are available for Cloudflare's Linux (x86, x86_64, ARM, ARMHF, ARM64), Windows (x86, x86_64), and macOS (Intel, Apple Silicon) releases.

After the public URL is printed prominently, qshare displays a terminal QR code for the same link. qshare accepts only a valid share hostname such as `https://department-specialists-excellence-savings.trycloudflare.com`; Cloudflare API URLs are rejected and the tunnel is retried. On Unix-like systems it then prompts: `Run in background? Press 'd' to detach, or press Enter to keep in the foreground.` Windows always runs in the foreground. When the TTL expires in foreground mode, qshare prints a notification and stops the share.

## Build for PyPI

```bash
uv build
python scripts/build_platform_wheels.py --assets-dir /path/to/cloudflared-assets
```

Then upload the resulting artifacts from the `dist/` directory to PyPI.

## Notes

- The default lifetime is 2 hours.
- If a port is occupied, qshare automatically selects another free port.
- `--ttl` accepts values like `30m`, `90s`, `2h`, or a plain number in seconds.
- Background mode is triggered by entering `d` at the interactive prompt after the public URL appears.
