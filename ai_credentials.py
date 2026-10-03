"""Windows-only encrypted storage for the user's AI API key.

The credential is protected with Windows DPAPI and is never written to disk as
plaintext.  New files use local-machine DPAPI scope so a key written by the
packaged desktop process remains readable after relaunch.  The encrypted file
still lives inside the current user's LocalAppData directory.  Callers may pass
an explicit path (or set ``SHULIAN_CREDENTIALS_FILE``) to isolate tests and
development instances.
"""

from __future__ import annotations

import ctypes
import os
import tempfile
from ctypes import wintypes
from pathlib import Path


_MAGIC_V1 = b"SHULIAN-CREDENTIAL\x00\x01"
_MAGIC_V2 = b"SHULIAN-CREDENTIAL\x00\x02"
_MAX_FILE_BYTES = 64 * 1024
_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_CRYPTPROTECT_LOCAL_MACHINE = 0x04


class CredentialError(RuntimeError):
    """The encrypted credential could not be read or updated."""


class CredentialUnavailableError(CredentialError):
    """DPAPI is unavailable on the current platform."""


class CredentialCorruptError(CredentialError):
    """The credential file is malformed or cannot be decrypted."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def credential_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Return the credential file path without creating it."""
    if path is not None:
        return Path(path).expanduser()

    override = os.getenv("SHULIAN_CREDENTIALS_FILE", "").strip()
    if override:
        return Path(override).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        root = Path(local_app_data)
    else:
        root = Path.home() / "AppData" / "Local"
    return root / "Shulian" / "credentials.bin"


def credentials_exist(path: str | os.PathLike[str] | None = None) -> bool:
    return credential_path(path).is_file()


def _windows_libraries():
    if os.name != "nt":
        raise CredentialUnavailableError("Windows DPAPI is unavailable")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _input_blob(payload: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(payload, len(payload))
    blob = _DataBlob(
        len(payload),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _protect_data(payload: bytes, *, machine_scope: bool = False) -> bytes:
    crypt32, kernel32 = _windows_libraries()
    input_blob, input_buffer = _input_blob(payload)
    output_blob = _DataBlob()
    try:
        flags = _CRYPTPROTECT_UI_FORBIDDEN
        if machine_scope:
            flags |= _CRYPTPROTECT_LOCAL_MACHINE
        if not crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "Shulian AI credential",
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        ):
            raise CredentialError(
                f"DPAPI encryption failed with Windows error {ctypes.get_last_error()}"
            )
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.memset(input_buffer, 0, len(payload))
        if output_blob.pbData:
            kernel32.LocalFree(output_blob.pbData)


def _unprotect_data(payload: bytes) -> bytes:
    crypt32, kernel32 = _windows_libraries()
    input_blob, input_buffer = _input_blob(payload)
    output_blob = _DataBlob()
    try:
        if not crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        ):
            raise CredentialCorruptError(
                f"DPAPI decryption failed with Windows error {ctypes.get_last_error()}"
            )
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.memset(input_buffer, 0, len(payload))
        if output_blob.pbData:
            kernel32.LocalFree(output_blob.pbData)


def save_api_key(
    api_key: str,
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Encrypt and atomically persist one API key."""
    normalized = api_key.strip()
    if not normalized:
        raise ValueError("API key cannot be empty")

    plaintext = bytearray(normalized.encode("utf-8"))
    try:
        encrypted = _protect_data(bytes(plaintext), machine_scope=True)
    finally:
        for index in range(len(plaintext)):
            plaintext[index] = 0

    target = credential_path(path)
    temp_path: str | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        with os.fdopen(descriptor, "wb") as credential_file:
            credential_file.write(_MAGIC_V2)
            credential_file.write(encrypted)
            credential_file.flush()
            os.fsync(credential_file.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, target)
        temp_path = None
    except CredentialError:
        raise
    except OSError as exc:
        raise CredentialError("Unable to save encrypted credential") from exc
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass


def load_api_key(
    path: str | os.PathLike[str] | None = None,
) -> str | None:
    """Load and decrypt the API key, or return ``None`` when absent."""
    target = credential_path(path)
    try:
        file_size = target.stat().st_size
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CredentialError("Unable to inspect encrypted credential") from exc

    if file_size <= min(len(_MAGIC_V1), len(_MAGIC_V2)) or file_size > _MAX_FILE_BYTES:
        raise CredentialCorruptError("Credential file has an invalid size")

    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise CredentialError("Unable to read encrypted credential") from exc
    if payload.startswith(_MAGIC_V2):
        encrypted_payload = payload[len(_MAGIC_V2) :]
    elif payload.startswith(_MAGIC_V1):
        encrypted_payload = payload[len(_MAGIC_V1) :]
    else:
        raise CredentialCorruptError("Credential file has an invalid format")

    plaintext = bytearray(_unprotect_data(encrypted_payload))
    try:
        api_key = plaintext.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise CredentialCorruptError("Credential contents are invalid") from exc
    finally:
        for index in range(len(plaintext)):
            plaintext[index] = 0

    if not api_key:
        raise CredentialCorruptError("Credential contents are empty")
    return api_key


def delete_api_key(path: str | os.PathLike[str] | None = None) -> None:
    """Remove the encrypted credential file when it exists."""
    try:
        credential_path(path).unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CredentialError("Unable to remove encrypted credential") from exc
