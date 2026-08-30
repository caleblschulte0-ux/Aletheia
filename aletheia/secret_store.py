"""Local-only secret storage using Windows DPAPI.

Secrets such as API keys must never enter the public GitHub command bus, repo,
journal, model prompt, or screenshots. This store encrypts plaintext with the
current Windows user's DPAPI key and writes only ciphertext under Aletheia's
private local state directory.

There is intentionally no CLI command that prints a stored secret. Internal
local capabilities can resolve an alias with `get()` when they need to inject a
credential directly into an authenticated local operation.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

from aletheia import stateio

ROOT = stateio.private_dir("secrets")
MAX_SECRET_BYTES = 64 * 1024
ENTROPY = b"Aletheia local secret store v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretStoreUnavailable(RuntimeError):
    pass


class SecretStoreError(RuntimeError):
    pass


def available() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "Windows DPAPI is only available on Windows"
    try:
        ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    except Exception as exc:
        return False, f"DPAPI libraries unavailable ({type(exc).__name__})"
    return True, "Windows DPAPI ready"


def _require_windows() -> None:
    ok, why = available()
    if not ok:
        raise SecretStoreUnavailable(why)


def _protect(data: bytes) -> bytes:
    """Encrypt bytes for the current Windows user with app-specific entropy."""
    _require_windows()

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def blob(raw: bytes):
        buf = ctypes.create_string_buffer(raw)
        value = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        return value, buf

    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_bool
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    source, source_buf = blob(data)
    entropy, entropy_buf = blob(ENTROPY)
    del source_buf, entropy_buf  # structures keep their pointer values for this call
    out = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "Aletheia", ctypes.byref(entropy), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
    ):
        raise SecretStoreError(f"CryptProtectData failed ({ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        if out.pbData:
            kernel32.LocalFree(out.pbData)


def _unprotect(data: bytes) -> bytes:
    """Decrypt bytes for the same Windows user; never logs plaintext."""
    _require_windows()

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def blob(raw: bytes):
        buf = ctypes.create_string_buffer(raw)
        value = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        return value, buf

    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_bool
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    source, source_buf = blob(data)
    entropy, entropy_buf = blob(ENTROPY)
    del source_buf, entropy_buf
    out = DATA_BLOB()
    description = ctypes.c_wchar_p()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), ctypes.byref(description), ctypes.byref(entropy), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
    ):
        raise SecretStoreError(f"CryptUnprotectData failed ({ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        if out.pbData:
            kernel32.LocalFree(out.pbData)
        if description:
            kernel32.LocalFree(description)


def _paths(name: str) -> tuple[Path, Path]:
    safe = stateio.safe_id(name, name="secret name")
    return ROOT / f"{safe}.bin", ROOT / f"{safe}.json"


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def put(name: str, secret: str, *, provider: str = "", kind: str = "secret") -> dict:
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    raw = secret.encode("utf-8")
    if len(raw) > MAX_SECRET_BYTES:
        raise ValueError(f"secret exceeds {MAX_SECRET_BYTES} bytes")
    cipher_path, meta_path = _paths(name)
    encrypted = _protect(raw)
    if not encrypted or raw in encrypted:
        raise SecretStoreError("DPAPI did not produce opaque ciphertext")
    _write_bytes_atomic(cipher_path, encrypted)
    previous = None
    if meta_path.is_file():
        try:
            previous = stateio.read_json(meta_path)
        except ValueError:
            previous = None
    now = stateio.utcnow()
    metadata = {
        "version": 1,
        "name": stateio.safe_id(name, name="secret name"),
        "provider": str(provider)[:160],
        "kind": str(kind)[:80],
        "created_at": (previous or {}).get("created_at", now),
        "updated_at": now,
        "ciphertext_file": cipher_path.name,
    }
    stateio.write_json_atomic(meta_path, metadata)
    return metadata


def get(name: str) -> str:
    cipher_path, _ = _paths(name)
    try:
        encrypted = cipher_path.read_bytes()
    except FileNotFoundError as exc:
        raise KeyError(name) from exc
    raw = _unprotect(encrypted)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretStoreError("stored secret is not valid UTF-8") from exc


def metadata(name: str) -> dict:
    _, meta_path = _paths(name)
    try:
        value = stateio.read_json(meta_path)
    except FileNotFoundError as exc:
        raise KeyError(name) from exc
    if not isinstance(value, dict):
        raise SecretStoreError("secret metadata is malformed")
    return value


def list_metadata() -> list[dict]:
    if not ROOT.is_dir():
        return []
    out = []
    for path in sorted(ROOT.glob("*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def delete(name: str) -> bool:
    cipher_path, meta_path = _paths(name)
    existed = cipher_path.exists() or meta_path.exists()
    for path in (cipher_path, meta_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return existed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local Windows-DPAPI secret aliases; never prints plaintext.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("list")
    put_p = sub.add_parser("put")
    put_p.add_argument("name")
    put_p.add_argument("--provider", default="")
    put_p.add_argument("--kind", default="secret")
    delete_p = sub.add_parser("delete")
    delete_p.add_argument("name")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        ok, why = available()
        print(f"secret store: {'ready' if ok else 'unavailable'} — {why}")
        return 0 if ok else 1
    if args.cmd == "list":
        for row in list_metadata():
            print(f"{row.get('name')}  {row.get('kind')}  {row.get('provider')}  updated={row.get('updated_at')}")
        return 0
    if args.cmd == "delete":
        print("deleted" if delete(args.name) else "not found")
        return 0

    secret = getpass.getpass("Secret (stored locally; not echoed): ")
    row = put(args.name, secret, provider=args.provider, kind=args.kind)
    print(f"stored {row['name']} ({row['kind']}) for {row['provider'] or 'local use'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
