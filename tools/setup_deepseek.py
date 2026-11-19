"""Prepare a disabled local DeepSeek profile and optionally check credentials."""

from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config/model_routes.deepseek.example.yaml"
DEFAULTS = ROOT / "config/deepseek.local.example.env"
KEY_ENV = "DeepSeek_ANTHROPIC_AUTH_TOKEN"


def read_user_key() -> str | None:
    """Read only the named user variable; never enumerate registry secrets."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, kind = winreg.QueryValueEx(key, KEY_ENV)
            if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str):
                return value.strip() or None
    except OSError:
        pass
    return None


def read_key() -> str | None:
    return os.environ.get(KEY_ENV, "").strip() or read_user_key()


def load_environment() -> None:
    # Nonsecret defaults only. Credentials are never read from files.
    allowed = {"DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL_FLASH"}
    for line in DEFAULTS.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name in allowed:
            os.environ.setdefault(name, value.strip())
    secret = read_key()
    if secret:
        os.environ[KEY_ENV] = secret


def prepare(target: Path, *, force: bool = False) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("w" if force else "x", encoding="utf-8") as stream:
            stream.write(PROFILE.read_text(encoding="utf-8"))
    except FileExistsError:
        return False
    return True


def check_models(base_url: str, secret: str | None, *, client: httpx.Client | None = None) -> int:
    if not secret:
        print("status=missing_credentials")
        return 1
    if client is None:
        with httpx.Client(follow_redirects=False, trust_env=False) as owned:
            return check_models(base_url, secret, client=owned)
    try:
        response = client.get(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=10,
            follow_redirects=False,
        )
        print(f"status={response.status_code}")
        if response.status_code != 200:
            return 1
        payload = response.json()
        identifiers = [entry["id"] for entry in payload["data"]]
        # Allow only identifier characters, never echo arbitrary response text.
        for identifier in identifiers:
            if (
                isinstance(identifier, str)
                and len(identifier) <= 100
                and all(
                    character.isascii() and (character.isalnum() or character in "-_./")
                    for character in identifier
                )
                and secret not in identifier
            ):
                print(f"model={identifier}")
        return 0
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        print("status=check_failed")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace local routes explicitly")
    parser.add_argument("--check", action="store_true", help="GET /models only; no generation")
    parser.add_argument("--run-api", action="store_true", help="Load environment and run local API")
    args = parser.parse_args()
    load_environment()
    target = ROOT / "config/model_routes.yaml"
    changed = prepare(target, force=args.force)
    print("Local profile created." if changed else "Existing local profile preserved.")
    print(
        "Prepared profile keeps external calls disabled; formal flow requires approval and verified pricing."
    )
    if args.check:
        result = check_models(os.environ["DEEPSEEK_BASE_URL"], read_key())
        if result:
            return result
    if args.run_api:
        os.environ["TUTOR_MODEL_ROUTES_PATH"] = str(target)
        sys.argv = [str(ROOT / "tools/run_dev_api.py")]
        runpy.run_path(sys.argv[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
