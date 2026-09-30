import argparse
import builtins
import os
import posixpath
import re
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import pathname2url

from functools import partial
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

DEFAULT_TTL_SECONDS = 2 * 60 * 60


def _text_for_stream(value: object, stream: object) -> str:
    text = str(value)
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except (LookupError, UnicodeEncodeError):
        try:
            return text.encode(encoding, "replace").decode(encoding, "replace")
        except (LookupError, UnicodeEncodeError):
            return text.encode("ascii", "replace").decode("ascii")


def _safe_print(*values: object, **kwargs: object) -> None:
    stream = kwargs.get("file") or sys.stdout
    values = tuple(_text_for_stream(value, stream) for value in values)
    builtins.print(*values, **kwargs)


# Python 3.6 may inherit an ASCII stdout/stderr encoding from the host.
print = _safe_print


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
    for match in re.finditer(r"https://(?P<host>[A-Za-z0-9-]+\.trycloudflare\.com)", output, re.IGNORECASE):
        if match.group("host").lower() != "api.trycloudflare.com":
            return match.group(0)
    return None


def build_download_url(base_url: str, file_name: str) -> str:
    cleaned_base = base_url.rstrip("/")
    cleaned_name = file_name.lstrip("/")
    return f"{cleaned_base}/{cleaned_name}"


def _load_qrcode():
    import qrcode

    return qrcode


def print_qr_code(url: str) -> bool:
    """Render a QR code when possible without affecting the active share."""
    try:
        qrcode = _load_qrcode()
        qr = qrcode.QRCode(
            # A four-module quiet zone is required by the QR specification and
            # lets ordinary camera apps reliably detect the finder patterns.
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        print("Scan this QR code to open the public file URL:")
        if os.name == "nt":
            # Console character cells vary by CMD/PowerShell font and scaling, so
            # a camera cannot reliably decode a character-art QR code.  Write a
            # standards-compliant vector QR instead; browsers render every module
            # as a true square and can be scanned from the screen.
            matrix = qr.get_matrix()
            size = len(matrix)
            modules = []
            for row, values in enumerate(matrix):
                for col, module in enumerate(values):
                    if module:
                        modules.append('<rect x="{}" y="{}" width="1" height="1"/>'.format(col, row))
            svg = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {0} {0}" '
                'shape-rendering="crispEdges">\n'
                '<rect width="100%" height="100%" fill="white"/>\n'
                '<g fill="black">{1}</g>\n</svg>\n'
            ).format(size, "".join(modules))
            path = os.path.join(tempfile.gettempdir(), "qshare-qr-{}.svg".format(uuid.uuid4().hex[:10]))
            with open(path, "w", encoding="utf-8") as output:
                output.write(svg)
            print("Windows QR code saved to: {}".format(path))
            print("It is opening in your browser; scan the displayed QR code with your camera.")
            try:
                webbrowser.open(urljoin("file:", pathname2url(path)))
            except (OSError, ValueError):
                pass
            return True
        # qrcode's terminal renderer packs two QR rows into one character row.
        # It handles the quiet zone consistently in CMD, PowerShell, and Unix
        # terminals without platform-specific character stretching.
        qr.print_ascii(invert=True)
        return True
    except Exception as exc:
        print("QR code unavailable: {}. Use the public URL shown above.".format(exc), file=sys.stderr)
        return False


class ShareHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        # ``directory=`` was added to SimpleHTTPRequestHandler in Python 3.7.
        # Store it ourselves so Python 3.6 can serve the selected file's
        # parent directory without changing the process working directory.
        self._share_directory = kwargs.pop("directory", os.getcwd())
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def translate_path(self, path: str) -> str:
        """Resolve request paths below the configured share directory."""
        path = posixpath.normpath(unquote(urlparse(path).path))
        words = [word for word in path.split("/") if word]
        translated = str(self._share_directory)
        for word in words:
            if os.path.dirname(word) or word in (os.curdir, os.pardir):
                continue
            translated = os.path.join(translated, word)
        return translated

    def copyfile(self, source: object, outputfile: object) -> None:
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # The client may cancel a download or close its browser tab.
            # That is not a server failure and should not print a traceback.
            return


class ShareHTTPServer(ThreadingMixIn, HTTPServer):
    # ThreadingHTTPServer was added in Python 3.7.  This is its Python 3.6
    # compatible equivalent.
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        # A browser cancelling a download can reset the TCP connection while
        # the response is being written. It must not affect the server.
        exc_type, exc_value, _ = sys.exc_info()
        if isinstance(exc_value, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def start_local_http_server(file_path: Path, port: int) -> Tuple[ShareHTTPServer, threading.Thread]:
    if not file_path.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")

    server = ShareHTTPServer(("127.0.0.1", port), partial(ShareHandler, directory=str(file_path.parent)))
    thread = threading.Thread(target=server.serve_forever, name="qshare-http", daemon=True)
    thread.start()
    return server, thread


def stop_local_http_server(server: ShareHTTPServer) -> None:
    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass


def get_bundled_cloudflared_binary() -> Path:
    name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    bundled = Path(__file__).resolve().parent / "_binaries" / name
    if not bundled.is_file():
        raise RuntimeError(
            "This qshare installation has no bundled cloudflared binary for this platform. "
            "Install qshare from PyPI on a supported platform, or install cloudflared yourself and add it to PATH."
        )
    return bundled


def install_cloudflared_binary() -> str:
    target_dir = Path.home() / ".local" / "bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("cloudflared.exe" if os.name == "nt" else "cloudflared")

    if target.exists():
        return str(target)

    try:
        print("cloudflared was not found. Installing the binary bundled with qshare...")
        shutil.copyfile(str(get_bundled_cloudflared_binary()), str(target))
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
    deadline = time.monotonic() + timeout_seconds
    for attempt in range(3):
        logfile = Path(tempfile.gettempdir()) / f"qshare-{uuid.uuid4().hex}.log"
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "universal_newlines": True,
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        process = subprocess.Popen(
            [cloudflared_path, "tunnel", "--url", local_url, "--no-autoupdate", "--logfile", str(logfile)],
            **kwargs,
        )
        if process.stdout is None:
            raise RuntimeError("Unable to capture cloudflared output.")

        attempt_deadline = min(deadline, time.monotonic() + 10)
        while time.monotonic() < attempt_deadline:
            line = process.stdout.readline()
            if line:
                url = extract_trycloudflare_url(line)
                if url:
                    return process, url
                continue
            if process.poll() is not None:
                break
            time.sleep(0.2)

        stop_tunnel(process)
        if time.monotonic() < deadline and attempt < 2:
            print("Cloudflare did not provide a valid public URL; retrying...")

    raise TimeoutError(f"Timed out waiting for a valid public TryCloudflare URL in {timeout_seconds} seconds.")


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

    detached = False

    def stop_all() -> None:
        stop_event.set()
        if tunnel_process is not None:
            stop_tunnel(tunnel_process)
        stop_local_http_server(server)
        if server_thread.is_alive():
            server_thread.join(timeout=2)

    def expire() -> None:
        if not detached:
            print("TTL expired; the public share has stopped.", flush=True)
        stop_all()

    timer = threading.Timer(ttl_seconds, expire)
    timer.daemon = True
    timer.start()

    try:
        tunnel_process, tunnel_url = launch_trycloudflare_tunnel(local_url, timeout_seconds=min(ttl_seconds, 30))
        public_file_url = build_download_url(tunnel_url, source.name)
        print("\n" + "=" * 72)
        print(f"PUBLIC FILE URL: {public_file_url}")
        print("=" * 72 + "\n", flush=True)
        print_qr_code(public_file_url)
        # A detached child is already the background worker.  Prompting it
        # again (with stdin connected to DEVNULL) makes it take the
        # foreground path accidentally and, more importantly, used to make
        # the hand-off look as if the original service had simply died.
        if os.name != "nt" and os.environ.get("QSHARE_BACKGROUND_CHILD") != "1" and ask_background_mode():
            handoff = detach_existing_process(server)
            if handoff is True:
                # Parent exits, while the child keeps the inherited server
                # socket and cloudflared process (therefore the same URL).
                detached = True
                return 0
            if handoff is None:
                # Windows cannot safely detach this interpreter from its
                # console while retaining the inherited server/tunnel. Keep
                # this process running instead of launching a replacement
                # qshare (which would change the tunnel URL).
                if os.name == "nt":
                    detached = True
                    print("Running in background mode; keep this window open to retain the same URL.")
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
            detached = True
            tunnel_process = DetachedTunnelProcess(tunnel_process.pid)
            timer = threading.Timer(ttl_seconds, expire)
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
    parser.add_argument(
        "--cnb",
        action="store_true",
        help="Upload the file to the configured CNB release instead of sharing through TryCloudflare.",
    )
    return parser


def print_privacy_warning() -> None:
    line = "!" * 72
    print("\n" + line)
    warning = "!!! 重要安全提示 / IMPORTANT SECURITY WARNING !!!"
    reminder = "私密文件请先加密，再进行中转分享。公网链接没有访问控制。"
    if _text_for_stream(warning, sys.stdout) == warning and _text_for_stream(reminder, sys.stdout) == reminder:
        print(warning)
        print(reminder)
    else:
        print("IMPORTANT SECURITY WARNING: Encrypt private files before transferring them.")
    print("Encrypt private files before transferring them. Public URLs have no access control.")
    print(line)


def confirm_cnb_upload() -> bool:
    try:
        prompt = "确认将文件上传到 CNB 并存储在那里吗？输入 y 确认 / Confirm upload (y/N): "
        if _text_for_stream(prompt, sys.stdout) != prompt:
            prompt = "Confirm upload to CNB (y/N): "
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() == "y"


def run_cnb_upload(file_path: str) -> int:
    source = Path(file_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError("File not found: {}".format(source))
    from .cnb import upload_to_cnb

    print("Uploading file to CNB Release; the file will be stored there.", flush=True)
    public_url = upload_to_cnb(str(source))
    print("\n" + "=" * 72)
    print("PUBLIC FILE URL: {}".format(public_url))
    print("=" * 72 + "\n", flush=True)
    print_qr_code(public_url)
    return 0


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


def detach_existing_process(server: ShareHTTPServer) -> Optional[bool]:
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


def ask_background_mode() -> bool:
    try:
        answer = input("Run in background? Press 'd' to detach, or press Enter to keep in the foreground: ")
    except EOFError:
        return False
    return should_run_in_background(answer)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    print_privacy_warning()

    if args.cnb:
        if not confirm_cnb_upload():
            print("已取消上传 / Upload cancelled.")
            return 0
        try:
            return run_cnb_upload(args.file)
        except KeyboardInterrupt:
            print("\nUpload cancelled.")
            return 130
        except Exception as exc:  # pragma: no cover - CLI-level output
            print("qshare error: {}".format(exc), file=sys.stderr)
            return 1

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
