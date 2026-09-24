# qshare

Share a local file to the public internet with one command, without an account or login.
The file is served by your own machine through a temporary TryCloudflare tunnel and is not
stored on a qshare server.

## Features

- No account or login required
- One-command sharing of a local file
- Files are not retained by qshare
- Configurable TTL, two hours by default
- Prominent public URL and terminal QR code
- Linux, Windows, and macOS support
- Platform-specific PyPI wheels containing the matching official `cloudflared` binary
- No runtime download from GitHub

On startup qshare reminds you to encrypt private files before transferring them. Public URLs
have no access control, so do not share sensitive files without encryption.

## Installation

```bash
python -m pip install -U qshare
```

pip selects the wheel matching the operating system and architecture. Each wheel contains
only the binary for its own platform.

If you do not trust the binary bundled in the PyPI wheel, download the matching binary from
Cloudflare's official release page, verify its published checksum, and put it in `PATH`:

<https://github.com/cloudflare/cloudflared/releases>

qshare prefers an existing `cloudflared` executable in `PATH`. Manual installation is also
required on platforms without a matching qshare wheel.

## Usage

```bash
qshare /path/to/file.zip
qshare /path/to/file.zip --ttl 2h
qshare /path/to/file.zip --ttl 900
qshare /path/to/file.zip --port 8000
qshare /path/to/file.zip --cnb
```

qshare displays a prominent public URL and a terminal QR code. It accepts only a real
`*.trycloudflare.com` share hostname, rejects `api.trycloudflare.com`, and retries. On
Unix-like systems, enter `d` at the prompt to run in the background; Windows always runs in
the foreground. A foreground share prints a notice and stops when its TTL expires.

With `--cnb`, qshare uploads the file to a CNB Release and prints its download URL. The file
is stored in CNB; encrypt private files first. Upload progress is shown while transferring.
The CNB channel is useful when you need a persistent download URL or Cloudflare is unreliable.
qshare asks for explicit confirmation before uploading and starts only when you enter `y`.
Files in the CNB Release are not deleted automatically by qshare; manage them as needed.

## DNS troubleshooting

If the URL reports that its IP address cannot be found, the issue is often local DNS
resolution or network filtering. Try Cloudflare DNS (`1.1.1.1` and `1.0.0.1`) or Google DNS
(`8.8.8.8` and `8.8.4.4`), flush the local DNS cache, and retry. Changing DNS may improve
resolution, but it cannot fix an expired tunnel or a network that blocks Cloudflare.

## Development and release

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
PYTHONPATH=src pytest -q
```

Build platform wheels from locally prepared Cloudflare assets:

```bash
uv build
python scripts/build_platform_wheels.py --assets-dir /path/to/cloudflared-assets
```
