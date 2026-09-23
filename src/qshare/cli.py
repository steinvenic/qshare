import argparse
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

DEFAULT_TTL_SECONDS = 2 * 60 * 60


def parse_duration(value: Union[str, int, float]) -> int:
    """Convert duration strings like 30m, 90s, 2h to seconds."""
    if isinstance(value, (int, float)):
        seconds = int(value)
        if seconds <= 0:
            raise ValueError("Duration must be positive.")
        return seconds

    text = str(value).strip().lower()
    if not text:
        raise ValueError("Duration is required.")

    if text.isdigit():
        return int(text)

    match = re.fullmatch(r"(?P<number>\d+)(?P<unit>[smhd]?)", text)
    if not match:
        raise ValueError(f"Unsupported duration: {value!r}. Use 30m, 90s, 2h, or plain seconds.")

    number = int(match.group("number"))
    unit = match.group("unit") or "s"
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = number * multipliers[unit]
    if seconds <= 0:
        raise ValueError("Duration must be greater than zero.")
    return seconds


def find_available_port(
    start_port: int = 20000,
    end_port: int = 65535,
    used_ports: Optional[Iterable[int]] = None,
) -> int:
    """Return a free localhost port, avoiding the given ports."""
    blacklisted = set(used_ports or [])
    ports = list(range(start_port, end_port + 1))
    import random

    random.shuffle(ports)
    for port in ports:
        if port in blacklisted:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OSError(f"No free port found between {start_port} and {end_port}.")


def extract_trycloudflare_url(output: str) -> Optional[str]:
    match = re.search(r"https?://[A-Za-z0-9.-]+\.trycloudflare\.com", output)
    if match:
        return match.group(0)
    return None


def build_download_url(base_url: str, file_name: str) -> str:
    cleaned_base = base_url.rstrip("/")
    cleaned_name = file_name.lstrip("/")
    return f"{cleaned_base}/{cleaned_name}"


class ShareHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def start_local_http_server(file_path: Path, port: int) -> Tuple[ThreadingHTTPServer, threading.Thread]:
    if not file_path.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")

    server = ThreadingHTTPServer(("127.0.0.1", port), partial(ShareHandler, directory=str(file_path.parent)))
    thread = threading.Thread(target=server.serve_forever, name="qshare-http", daemon=True)
    thread.start()
    return server, thread


def stop_local_http_server(server: ThreadingHTTPServer) -> None:
    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass


def get_cloudflared_download_url() -> str:
    override = os.getenv("CLOUDFLARED_DOWNLOAD_URL")
    if override:
        return override.strip()

    system = platform.system().lower()
    machine = platform.machine().lower()
    mapping = {
        ("linux", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
        ("linux", "amd64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
        ("linux", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
        ("linux", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
        ("windows", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        ("windows", "amd64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        ("windows", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-arm64.exe",
        ("windows", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-arm64.exe",
    }
    key = (system, machine)
    if key not in mapping:
        raise RuntimeError(
            f"Unsupported platform for automatic cloudflared install: {system}/{machine}. "
            "Please install cloudflared manually: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
        )
    return mapping[key]


def install_cloudflared_binary() -> str:
    target_dir = Path.home() / ".local" / "bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "cloudflared"

    if target.exists():
        return str(target)

    url = get_cloudflared_download_url()
    try:
        urllib.request.urlretrieve(url, str(target))
        if os.name != "nt":
            target.chmod(0o755)
        return str(target)
    except Exception:
        if target.exists():
            target.unlink()
        raise


def ensure_cloudflared() -> str:
    binary_path = shutil.which("cloudflared")
    if binary_path:
        return binary_path

    user_bin = Path.home() / ".local" / "bin" / "cloudflared"
    if user_bin.exists():
        return str(user_bin)

    installed = install_cloudflared_binary()
    os.environ["PATH"] = str(Path(installed).parent) + os.pathsep + os.environ.get("PATH", "")
    return installed


def launch_trycloudflare_tunnel(local_url: str, timeout_seconds: int) -> Tuple[subprocess.Popen, str]:
    cloudflared_path = ensure_cloudflared()
    logfile = Path(tempfile.gettempdir()) / f"qshare-{uuid.uuid4().hex}.log"
    process = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", local_url, "--no-autoupdate", "--logfile", str(logfile)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )

    if process.stdout is None:
        raise RuntimeError("Unable to capture cloudflared output.")

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                output = ""
                try:
                    output = process.stdout.read()
                except Exception:
                    output = ""
                raise RuntimeError(f"cloudflared exited before returning a tunnel URL.\n{output}")
            time.sleep(0.2)
            continue

        url = extract_trycloudflare_url(line)
        if url:
            return process, url

    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            pass

    raise TimeoutError(f"Timed out waiting for a public TryCloudflare URL in {timeout_seconds} seconds.")


def stop_tunnel(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def run_share(file_path: str, ttl_seconds: int = DEFAULT_TTL_SECONDS, port: Optional[int] = None) -> int:
    source = Path(file_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"File not found: {source}")
    if not source.is_file():
        raise ValueError(f"Not a file: {source}")

    resolved_port = port or find_available_port()
    server, server_thread = start_local_http_server(source, resolved_port)
    local_url = f"http://127.0.0.1:{resolved_port}/{source.name}"

    print(f"Local file: {source}")
    print(f"Local HTTP URL: {local_url}")
    print(f"Waiting for public TryCloudflare URL (ttl={ttl_seconds}s)...")

    tunnel_process = None
    tunnel_url = None
    stop_event = threading.Event()

    def stop_all() -> None:
        stop_event.set()
        if tunnel_process is not None:
            stop_tunnel(tunnel_process)
        stop_local_http_server(server)
        if server_thread.is_alive():
            server_thread.join(timeout=2)

    timer = threading.Timer(ttl_seconds, stop_all)
    timer.daemon = True
    timer.start()
    detached = False

    try:
        tunnel_process, tunnel_url = launch_trycloudflare_tunnel(local_url, timeout_seconds=min(ttl_seconds, 30))
        public_file_url = build_download_url(tunnel_url, source.name)
        print(f"Public file URL: {public_file_url}")
        if ask_background_mode():
            detached = True
            background_argv = [str(source)]
            background_argv.extend(["--ttl", str(ttl_seconds)])
            if port is not None:
                background_argv.extend(["--port", str(port)])
            return start_background_process(background_argv)
        while not stop_event.is_set() and tunnel_process.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        stop_all()
        return 0
    except Exception:
        stop_all()
        raise
    finally:
        timer.cancel()
        if not detached:
            stop_all()

    return 0


def should_run_in_background(answer: str) -> bool:
    return str(answer or "").strip().lower() == "d"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quickly share a local file over a public TryCloudflare tunnel.",
        prog="qshare",
    )
    parser.add_argument("file", help="Local file to share publicly.")
    parser.add_argument(
        "-t",
        "--ttl",
        default="2h",
        help="How long the tunnel remains active. Examples: 2h, 30m, 90s, or 600 (seconds).",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,
        help="Optional fixed port for the local HTTP server. A random free port is used when omitted.",
    )
    return parser


def start_background_process(argv: List[str]) -> int:
    cmd = [sys.executable, "-m", "qshare"] + argv
    env = os.environ.copy()
    env["QSHARE_BACKGROUND_CHILD"] = "1"
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env,
    }
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    print("qshare started in background.")
    return 0


def ask_background_mode() -> bool:
    try:
        answer = input("Run in background? Press 'd' to detach, or press Enter to keep in the foreground: ")
    except EOFError:
        return False
    return should_run_in_background(answer)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if os.environ.get("QSHARE_BACKGROUND_CHILD") == "1":
        try:
            ttl_seconds = parse_duration(args.ttl)
            return run_share(args.file, ttl_seconds=ttl_seconds, port=args.port)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 130
        except Exception as exc:  # pragma: no cover - CLI-level output
            print(f"qshare error: {exc}", file=sys.stderr)
            return 1

    try:
        ttl_seconds = parse_duration(args.ttl)
        return run_share(args.file, ttl_seconds=ttl_seconds, port=args.port)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:  # pragma: no cover - CLI-level output
        print(f"qshare error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
