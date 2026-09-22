import socket

import pytest

from qshare.cli import (
    build_download_url,
    build_parser,
    extract_trycloudflare_url,
    find_available_port,
    get_cloudflared_download_url,
    parse_duration,
)


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


def test_parser_defaults_to_two_hour_ttl_and_supports_daemon_mode():
    parser = build_parser()
    args = parser.parse_args(["/tmp/demo.zip"])
    assert args.ttl == "2h"
    assert args.daemon is False

    daemon_args = parser.parse_args(["/tmp/demo.zip", "--daemon"])
    assert daemon_args.daemon is True


def test_get_cloudflared_download_url_uses_env_override(monkeypatch):
    monkeypatch.setenv("CLOUDFLARED_DOWNLOAD_URL", "https://example.com/mirror/cloudflared-linux-amd64")
    assert get_cloudflared_download_url() == "https://example.com/mirror/cloudflared-linux-amd64"


def test_build_download_url_joins_base_and_filename():
    assert build_download_url("https://abc.trycloudflare.com", "demo.zip") == "https://abc.trycloudflare.com/demo.zip"
    assert build_download_url("https://abc.trycloudflare.com/", "/demo.zip") == "https://abc.trycloudflare.com/demo.zip"
