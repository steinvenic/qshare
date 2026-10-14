"""One-time local verification for the bundled private CNB channel."""

import getpass
import hashlib
import hmac
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

from . import cnb
from .cli import _text_for_stream, print

PASSWORD_SALT = "cdad08d22fffa5ac0a67394981b619d3"
PASSWORD_DIGEST = "b52d9d8b7c392e1b4a76a991850cc437931e287dadedff4cd603600a1913f4c4"
PASSWORD_ITERATIONS = 210000


def verify_password(password: str) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(PASSWORD_SALT), PASSWORD_ITERATIONS
    ).hex()
    return hmac.compare_digest(digest, PASSWORD_DIGEST)


def auth_state_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    return root / "qshare" / "cnb-auth.json"


def _auth_scope() -> str:
    return hashlib.sha256(
        (cnb.DEFAULT_REPO + ":" + PASSWORD_DIGEST).encode("utf-8")
    ).hexdigest()


def _already_verified(path: Path) -> bool:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(state, dict) and state.get("verified") is True and state.get("scope") == _auth_scope()


def _save_verified(path: Path) -> None:
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(path.parent), prefix=".cnb-auth-", delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump({"verified": True, "scope": _auth_scope()}, output)
        temporary.replace(path)
    except OSError as exc:
        raise RuntimeError("Could not save CNB verification. Check permissions for {}.".format(path)) from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def print_first_use_notice() -> None:
    messages = [
        ("CNB 渠道为私人工具，首次使用需要验证密码。",
         "The CNB channel is a private tool. A password is required on first use."),
        ("可以 fork 本项目，设置 QSHARE_CNB_REPO 和自己的 QSHARE_CNB_TOKEN。",
         "You can fork this project and set QSHARE_CNB_REPO and your own QSHARE_CNB_TOKEN."),
        ("也可以加上 --cf 使用 CF 通道。验证成功后，本机后续使用不再需要密码或此提示。",
         "Or add --cf to use the CF channel. After verification, this device will not ask again or show this notice."),
    ]
    for chinese, english in messages:
        if _text_for_stream(chinese, sys.stdout) == chinese:
            print(chinese)
        print(english)
    print("Project: https://github.com/steinvenic/qshare", flush=True)


def ensure_cnb_access() -> None:
    if cnb.TOKEN != cnb.DEFAULT_TOKEN:
        return
    path = auth_state_path()
    if _already_verified(path):
        return
    print_first_use_notice()
    prompt = "CNB 密码 / CNB password: "
    if _text_for_stream(prompt, sys.stderr) != prompt:
        prompt = "CNB password: "
    try:
        # Refuse getpass's echoing fallback when no usable terminal is available.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass(prompt)
    except (EOFError, getpass.GetPassWarning):
        raise RuntimeError(
            "CNB first-use verification needs an interactive terminal. "
            "Run it in a terminal, configure your own CNB token, or add --cf."
        )
    if not verify_password(password):
        raise RuntimeError("CNB 密码验证失败 / CNB password verification failed.")
    _save_verified(path)
