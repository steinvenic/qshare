import argparse
import os
import platform
import re
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tarfile
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


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the native clipboard when a system backend is available."""
    try:
        if os.name == "nt":
            import ctypes

            CF_UNICODETEXT = 13
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32
            if not user32.OpenClipboard(None):
                return False
            try:
                user32.EmptyClipboard()
                data = ctypes.create_unicode_buffer(text)
                handle = kernel32.GlobalAlloc(0x0002, ctypes.sizeof(data))
                if not handle:
                    return False
                ctypes.memmove(handle, ctypes.addressof(data), ctypes.sizeof(data))
                if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    kernel32.GlobalFree(handle)
                    return False
                return True
            finally:
                user32.CloseClipboard()

        if platform.system().lower() == "darwin":
            command = ["pbcopy"]
        elif shutil.which("wl-copy"):
            command = ["wl-copy"]
        elif shutil.which("xclip"):
            command = ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            command = ["xsel", "--clipboard", "--input"]
        else:
            return False
        subprocess.run(command, input=text, text=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


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
        ("linux", "i386"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-386",
        ("linux", "i686"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-386",
        ("linux", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
        ("linux", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
        ("linux", "armv6l"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm",
        ("linux", "armv7l"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf",
        ("linux", "armv8l"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-armhf",
        ("windows", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        ("windows", "amd64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        ("windows", "x86"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe",
        ("windows", "i386"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe",
        ("windows", "i686"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe",
        ("darwin", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        ("darwin", "amd64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        ("darwin", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
        ("darwin", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
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
    target = target_dir / ("cloudflared.exe" if os.name == "nt" else "cloudflared")

    if target.exists():
        return str(target)

    url = get_cloudflared_download_url()
    try:
        if url.endswith(".tgz"):
            with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as archive_file:
                archive_path = Path(archive_file.name)
            try:
                urllib.request.urlretrieve(url, str(archive_path))
                with tarfile.open(str(archive_path), "r:gz") as archive:
                    member = archive.getmember("cloudflared")
                    source = archive.extractfile(member)
                    if source is None:
                        raise RuntimeError("cloudflared archive does not contain its binary.")
                    with source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
            finally:
                try:
                    archive_path.unlink()
                except OSError:
                    pass
        else:
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

    user_bin = Path.home() / ".local" / "bin" / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
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


class DetachedTunnelProcess:
    """Minimal Popen-compatible handle for an inherited orphaned tunnel."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> Optional[int]:
        try:
            os.kill(self.pid, 0)
        except OSError:
            return 0
        return None

    def terminate(self) -> None:
        os.kill(self.pid, signal.SIGTERM)

    def wait(self, timeout: Optional[float] = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(["cloudflared"], timeout)
            time.sleep(0.1)
        return 0

    def kill(self) -> None:
        os.kill(self.pid, signal.SIGKILL)


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
        if copy_to_clipboard(public_file_url):
            print("Public URL copied to clipboard.")
        else:
            print("Could not copy the public URL to clipboard; please copy it manually.")
        # A detached child is already the background worker.  Prompting it
        # again (with stdin connected to DEVNULL) makes it take the
        # foreground path accidentally and, more importantly, used to make
        # the hand-off look as if the original service had simply died.
        if os.environ.get("QSHARE_BACKGROUND_CHILD") != "1" and ask_background_mode():
            handoff = detach_existing_process(server)
            if handoff is True:
                # Parent exits, while the child keeps the inherited server
                # socket and cloudflared process (therefore the same URL).
                detached = True
                return 0
            if handoff is None:
                # Keep the current process alive on Windows by releasing its
                # console.  This preserves both the listening socket and the
                # existing cloudflared process (and therefore its hostname).
                if os.name == "nt":
                    detach_windows_console()
                    detached = True
                    # Fall through to the normal lifetime loop.
                # Other non-fork platforms retain the independent-worker
                # fallback.
                detached = True
                background_argv = [str(source), "--ttl", str(ttl_seconds)]
                if port is not None:
                    background_argv.extend(["--port", str(port)])
                return start_background_process(background_argv)
            # Child: the pre-fork timer thread no longer exists, so recreate
            # it before entering the normal lifetime loop.
            tunnel_process = DetachedTunnelProcess(tunnel_process.pid)
            timer = threading.Timer(ttl_seconds, stop_all)
            timer.daemon = True
            timer.start()
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
        # Keep the child's status and (most importantly) its replacement
        # public URL visible to the user.  The parent URL belongs to the
        # short-lived process and cannot remain valid after hand-off.
        "stdout": None,
        "stderr": None,
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


def detach_existing_process(server: ThreadingHTTPServer) -> Optional[bool]:
    """Detach while retaining the existing HTTP socket and tunnel process.

    Returns True in the short-lived parent, False in the detached child, and
    None on platforms without fork support.
    """
    if os.name == "nt":
        return None
    if not hasattr(os, "fork"):
        return None
    child_pid = os.fork()
    if child_pid:
        return True

    # The serving thread does not survive fork.  Reuse the inherited socket
    # and start a replacement thread; the cloudflared Popen process is also
    # inherited, so its public hostname remains unchanged.
    os.setsid()
    try:
        with open(os.devnull, "rb") as null_in, open(os.devnull, "ab") as null_out:
            os.dup2(null_in.fileno(), sys.stdin.fileno())
            os.dup2(null_out.fileno(), sys.stdout.fileno())
            os.dup2(null_out.fileno(), sys.stderr.fileno())
    except (OSError, ValueError):
        pass
    threading.Thread(target=server.serve_forever, name="qshare-http", daemon=True).start()
    return False


def detach_windows_console() -> None:
    """Release the Windows console while leaving this process running."""
    import ctypes

    try:
        ctypes.windll.kernel32.FreeConsole()
    except (AttributeError, OSError):
        return
    for stream_name, mode in (("stdin", "r"), ("stdout", "w"), ("stderr", "w")):
        try:
            stream = open(os.devnull, mode)
            setattr(sys, stream_name, stream)
        except OSError:
            pass


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
