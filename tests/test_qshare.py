import socket
from pathlib import Path

import pytest

from qshare.cli import (
    build_download_url,
    build_parser,
    extract_trycloudflare_url,
    find_available_port,
    get_bundled_cloudflared_binary,
    install_cloudflared_binary,
    launch_trycloudflare_tunnel,
    parse_duration,
    run_share,
    should_run_in_background,
)


def test_share_handler_ignores_cancelled_download(monkeypatch):
    from qshare.cli import ShareHandler

    class Parent:
        def copyfile(self, source, outputfile):
            raise ConnectionResetError("client cancelled")

    monkeypatch.setattr("qshare.cli.SimpleHTTPRequestHandler.copyfile", Parent.copyfile)
    handler = object.__new__(ShareHandler)

    handler.copyfile(object(), object())


def test_parse_duration_accepts_common_units():
    assert parse_duration("30m") == 1800
    assert parse_duration("90s") == 90
    assert parse_duration("2h") == 7200
    assert parse_duration("120") == 120


def test_parse_duration_rejects_invalid_values():
    with pytest.raises(ValueError):
        parse_duration("abc")
    with pytest.raises(ValueError):
        parse_duration("-5m")


def test_build_parser_defaults_to_two_hours():
    args = build_parser().parse_args(["demo.txt"])
    assert args.ttl == "2h"
    assert not hasattr(args, "daemon")


def test_should_run_in_background_accepts_d_choice():
    assert should_run_in_background("d") is True
    assert should_run_in_background(" D ") is True
    assert should_run_in_background("") is False
    assert should_run_in_background("n") is False


def test_run_share_does_not_stop_server_when_detached(monkeypatch, tmp_path):
    file_path = tmp_path / "demo.txt"
    file_path.write_text("demo")
    server = object()
    thread = type("Thread", (), {"is_alive": lambda self: False})()
    stop_called = {"value": False}

    monkeypatch.setattr("qshare.cli.start_local_http_server", lambda *_args, **_kwargs: (server, thread))
    monkeypatch.setattr(
        "qshare.cli.launch_trycloudflare_tunnel",
        lambda *_args, **_kwargs: (type("Proc", (), {"poll": lambda self: None})(), "https://abc.trycloudflare.com"),
    )
    monkeypatch.setattr("qshare.cli.ask_background_mode", lambda: True)
    monkeypatch.setattr("qshare.cli.detach_existing_process", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("qshare.cli.start_background_process", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("qshare.cli.stop_local_http_server", lambda *_args, **_kwargs: stop_called.__setitem__("value", True))

    result = run_share(str(file_path), ttl_seconds=60, port=12345)

    assert result == 0
    assert stop_called["value"] is False


def test_run_share_uses_existing_process_when_detached(monkeypatch, tmp_path):
    file_path = tmp_path / "demo.txt"
    file_path.write_text("demo")
    server = object()
    thread = type("Thread", (), {"is_alive": lambda self: False})()
    detached_server = {"value": None}

    monkeypatch.setattr("qshare.cli.start_local_http_server", lambda *_args, **_kwargs: (server, thread))
    monkeypatch.setattr(
        "qshare.cli.launch_trycloudflare_tunnel",
        lambda *_args, **_kwargs: (type("Proc", (), {"poll": lambda self: None})(), "https://abc.trycloudflare.com"),
    )
    monkeypatch.setattr("qshare.cli.ask_background_mode", lambda: True)
    monkeypatch.setattr(
        "qshare.cli.detach_existing_process",
        lambda value: detached_server.__setitem__("value", value) or True,
    )
    monkeypatch.setattr(
        "qshare.cli.start_background_process",
        lambda *_args, **_kwargs: pytest.fail("should not start a replacement process"),
    )

    assert run_share(str(file_path), ttl_seconds=60, port=12345) == 0
    assert detached_server["value"] is server


def test_background_child_does_not_prompt_to_detach_again(monkeypatch, tmp_path, capsys):
    file_path = tmp_path / "demo.txt"
    file_path.write_text("demo")
    server = object()
    thread = type("Thread", (), {"is_alive": lambda self: False})()
    asked = {"value": False}
    qr_urls = []

    monkeypatch.setenv("QSHARE_BACKGROUND_CHILD", "1")
    monkeypatch.setattr("qshare.cli.start_local_http_server", lambda *_args, **_kwargs: (server, thread))
    monkeypatch.setattr(
        "qshare.cli.launch_trycloudflare_tunnel",
        lambda *_args, **_kwargs: (type("Proc", (), {"poll": lambda self: 0})(), "https://abc.trycloudflare.com"),
    )
    monkeypatch.setattr("qshare.cli.ask_background_mode", lambda: asked.__setitem__("value", True))
    monkeypatch.setattr("qshare.cli.print_qr_code", lambda url: qr_urls.append(url) or print("QR CODE"))

    assert run_share(str(file_path), ttl_seconds=60, port=12345) == 0
    assert asked["value"] is False
    assert qr_urls == ["https://abc.trycloudflare.com/demo.txt"]
    output = capsys.readouterr().out
    assert output.index("PUBLIC FILE URL:") < output.index("QR CODE")


def test_find_available_port_skips_occupied_ports():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    taken_port = occupied.getsockname()[1]

    port = find_available_port(used_ports={taken_port}, start_port=10000, end_port=10100)

    assert port != taken_port
    assert 10000 <= port <= 10100

    occupied.close()


def test_extract_trycloudflare_url_from_cloudflared_output():
    log = """2025-03-04T10:00:00Z INF Quick Tunnel URL: https://abc123.trycloudflare.com"""
    assert extract_trycloudflare_url(log) == "https://abc123.trycloudflare.com"


def test_extract_trycloudflare_url_rejects_cloudflare_api_url():
    assert extract_trycloudflare_url("https://api.trycloudflare.com") is None
    assert extract_trycloudflare_url("http://department.trycloudflare.com") is None


def test_tunnel_retries_after_cloudflare_api_url(monkeypatch):
    class Output:
        def __init__(self, lines):
            self.lines = iter(lines)

        def readline(self):
            return next(self.lines, "")

    class Process:
        def __init__(self, lines):
            self.stdout = Output(lines)

        def poll(self):
            return 0

    processes = [
        Process(["https://api.trycloudflare.com\n"]),
        Process(["https://api.trycloudflare.com\n"]),
        Process(["https://department.trycloudflare.com\n"]),
    ]
    monkeypatch.setattr("qshare.cli.ensure_cloudflared", lambda: "cloudflared")
    monkeypatch.setattr("qshare.cli.subprocess.Popen", lambda *_args, **_kwargs: processes.pop(0))

    process, url = launch_trycloudflare_tunnel("http://127.0.0.1:20000/file", timeout_seconds=30)

    assert url == "https://department.trycloudflare.com"
    assert process.poll() == 0


def test_print_qr_code_renders_the_public_url(monkeypatch):
    calls = []

    class QRCode:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def add_data(self, value):
            calls.append(("data", value))

        def make(self, **kwargs):
            calls.append(("make", kwargs))

        def print_ascii(self, **kwargs):
            calls.append(("print", kwargs))

    monkeypatch.setattr("qshare.cli.qrcode.QRCode", QRCode)

    from qshare.cli import print_qr_code

    print_qr_code("https://department.trycloudflare.com/file.zip")

    assert calls[0][1]["border"] == 1
    assert ("data", "https://department.trycloudflare.com/file.zip") in calls
    assert ("print", {"invert": True}) in calls


def test_install_cloudflared_binary_copies_bundled_binary(monkeypatch, tmp_path, capsys):
    bundled = tmp_path / "bundled-cloudflared"
    bundled.write_bytes(b"cloudflared")
    monkeypatch.setattr("qshare.cli.Path.home", lambda: tmp_path)
    monkeypatch.setattr("qshare.cli.get_bundled_cloudflared_binary", lambda: bundled)

    installed = install_cloudflared_binary()

    assert Path(installed).read_bytes() == b"cloudflared"
    assert "Installing the binary bundled with qshare" in capsys.readouterr().out


def test_get_bundled_cloudflared_binary_requires_platform_wheel(monkeypatch, tmp_path):
    monkeypatch.setattr("qshare.cli.Path.resolve", lambda self: tmp_path / "cli.py")

    with pytest.raises(RuntimeError, match="no bundled cloudflared binary"):
        get_bundled_cloudflared_binary()


def test_build_download_url_joins_base_and_filename():
    assert build_download_url("https://abc.trycloudflare.com", "demo.zip") == "https://abc.trycloudflare.com/demo.zip"
    assert build_download_url("https://abc.trycloudflare.com/", "/demo.zip") == "https://abc.trycloudflare.com/demo.zip"
