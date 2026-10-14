import getpass
import hashlib
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from qshare import cnb, cnb_auth, cli


@pytest.fixture
def first_use(monkeypatch, tmp_path):
    state_path = tmp_path / "config" / "qshare" / "cnb-auth.json"
    monkeypatch.setattr(cnb_auth, "auth_state_path", lambda: state_path)
    monkeypatch.setattr(cnb, "TOKEN", cnb.DEFAULT_TOKEN)
    monkeypatch.setattr(cnb, "REPO", cnb.DEFAULT_REPO)
    password = "test-only-password"
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(cnb_auth.PASSWORD_SALT), cnb_auth.PASSWORD_ITERATIONS
    ).hex()
    monkeypatch.setattr(cnb_auth, "PASSWORD_DIGEST", digest)
    return state_path, password


def test_first_use_verifies_once_and_persists_without_password(monkeypatch, first_use, capsys):
    state_path, password = first_use
    prompts = []
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: prompts.append(prompt) or password)

    cnb_auth.ensure_cnb_access()
    output = capsys.readouterr().out
    assert "私人工具" in output
    assert "fork" in output
    assert "QSHARE_CNB_TOKEN" in output
    assert "--cf" in output
    assert password not in output
    assert len(prompts) == 1
    assert json.loads(state_path.read_text())["verified"] is True
    assert password not in state_path.read_text()

    cnb_auth.ensure_cnb_access()
    assert capsys.readouterr().out == ""
    assert len(prompts) == 1


def test_wrong_password_stops_before_upload_and_can_retry(monkeypatch, first_use, tmp_path):
    state_path, password = first_use
    source = tmp_path / "sample.txt"
    source.write_text("sample")
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: "wrong")
    monkeypatch.setattr(cnb, "upload_to_cnb", lambda path: pytest.fail("upload before verification"))
    with pytest.raises(RuntimeError, match="verification failed"):
        cli.run_cnb_upload(str(source))
    assert not state_path.exists()

    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: password)
    cnb_auth.ensure_cnb_access()
    assert state_path.exists()


@pytest.mark.parametrize("error", [EOFError, getpass.GetPassWarning])
def test_no_interactive_terminal_never_uploads_or_saves_state(monkeypatch, first_use, error):
    state_path, unused_password = first_use
    def unavailable(prompt):
        raise error()
    monkeypatch.setattr(cnb_auth.getpass, "getpass", unavailable)
    with pytest.raises(RuntimeError, match="interactive terminal"):
        cnb_auth.ensure_cnb_access()
    assert not state_path.exists()


def test_getpass_echo_fallback_is_refused(monkeypatch, first_use):
    import warnings
    def fallback(prompt):
        warnings.warn("No terminal", getpass.GetPassWarning)
        pytest.fail("must not read an echoed password")
    monkeypatch.setattr(cnb_auth.getpass, "getpass", fallback)
    with pytest.raises(RuntimeError, match="interactive terminal"):
        cnb_auth.ensure_cnb_access()


@pytest.mark.parametrize("state", ["invalid JSON", "[]", '{"verified": true}', '{"verified": true, "scope": "old"}'])
def test_invalid_or_old_state_requires_verification(monkeypatch, first_use, state):
    state_path, password = first_use
    state_path.parent.mkdir(parents=True)
    state_path.write_text(state)
    prompts = []
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: prompts.append(prompt) or password)
    cnb_auth.ensure_cnb_access()
    assert len(prompts) == 1
    assert cnb_auth._already_verified(state_path)


def test_own_token_skips_private_channel_notice_and_password(monkeypatch, first_use, capsys):
    state_path, unused_password = first_use
    monkeypatch.setattr(cnb, "TOKEN", "own-token")
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: pytest.fail("private password for own token"))
    cnb_auth.ensure_cnb_access()
    assert capsys.readouterr().out == ""
    assert not state_path.exists()


def test_repo_override_with_default_token_still_requires_password(monkeypatch, first_use):
    state_path, unused_password = first_use
    monkeypatch.setattr(cnb, "REPO", "another/repo")
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: "wrong")
    with pytest.raises(RuntimeError, match="verification failed"):
        cnb_auth.ensure_cnb_access()
    assert not state_path.exists()


def test_cf_channel_does_not_use_cnb_verification(monkeypatch, first_use, capsys):
    monkeypatch.setattr(cnb_auth, "ensure_cnb_access", lambda: pytest.fail("CNB verification in CF"))
    calls = []
    monkeypatch.setattr(cli, "run_share", lambda path, **kwargs: calls.append((path, kwargs)) or 0)
    assert cli.main(["sample.txt", "--cf", "--ttl", "30m"]) == 0
    assert calls == [("sample.txt", {"ttl_seconds": 1800, "port": None})]
    assert "private tool" not in capsys.readouterr().out


def test_invalid_file_does_not_prompt_for_password(monkeypatch, first_use, tmp_path):
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: pytest.fail("password for missing file"))
    with pytest.raises(FileNotFoundError):
        cli.run_cnb_upload(str(tmp_path / "missing"))


def test_save_failure_stops_upload(monkeypatch, first_use, tmp_path):
    state_path, password = first_use
    source = tmp_path / "sample.txt"
    source.write_text("sample")
    state_path.parent.mkdir(parents=True)
    state_path.mkdir()
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: password)
    monkeypatch.setattr(cnb, "upload_to_cnb", lambda path: pytest.fail("upload before saving verification"))
    with pytest.raises(RuntimeError, match="Could not save"):
        cli.run_cnb_upload(str(source))
    assert list(state_path.parent.iterdir()) == [state_path]


def test_first_use_notice_and_prompt_work_with_ascii_streams(monkeypatch, first_use):
    state_path, password = first_use
    class AsciiStream(StringIO):
        encoding = "ascii"
    output = AsciiStream()
    monkeypatch.setattr(cnb_auth.sys, "stdout", output)
    monkeypatch.setattr(cnb_auth.sys, "stderr", AsciiStream())
    prompts = []
    monkeypatch.setattr(cnb_auth.getpass, "getpass", lambda prompt: prompts.append(prompt) or password)
    cnb_auth.ensure_cnb_access()
    output.getvalue().encode("ascii")
    assert "private tool" in output.getvalue()
    assert "--cf" in output.getvalue()
    assert prompts == ["CNB password: "]


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_auth_state_uses_per_user_location(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(cnb_auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cnb_auth.sys, "platform", platform)
    monkeypatch.setattr(cnb_auth, "os", SimpleNamespace(
        name="nt" if platform == "win32" else "posix",
        environ={"XDG_CONFIG_HOME": str(tmp_path / "xdg"), "APPDATA": str(tmp_path / "appdata")},
    ))
    root = {
        "linux": tmp_path / "xdg",
        "darwin": tmp_path / "Library" / "Application Support",
        "win32": tmp_path / "appdata",
    }[platform]
    assert cnb_auth.auth_state_path() == root / "qshare" / "cnb-auth.json"


def test_configured_cnb_repo_and_token_are_used(monkeypatch):
    import os
    import subprocess
    import sys
    env = dict(os.environ, QSHARE_CNB_TOKEN="own-token", QSHARE_CNB_REPO="owner/fork")
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = source_root
    script = (
        'from qshare import cnb; '
        'assert cnb.API == "https://api.cnb.cool/owner/fork"; '
        'assert cnb.TOKEN == "own-token"'
    )
    subprocess.run([sys.executable, "-c", script], env=env, check=True)
