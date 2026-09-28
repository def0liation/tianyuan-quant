import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


SECRET_REF_PREFIX = "runtime-secret:v1:"
SECRET_KEY_ENV_NAMES = ("AGENT_RUNTIME_SECRET_KEY", "SUPER_RUNTIME_SECRET_KEY", "SUPER_SECRET_KEY")
PREVIOUS_SECRET_KEY_ENV_NAMES = (
    "AGENT_RUNTIME_SECRET_KEY_PREVIOUS",
    "SUPER_RUNTIME_SECRET_KEY_PREVIOUS",
    "SUPER_SECRET_KEY_PREVIOUS",
)
KEY_FILE_NAME = "agent_runtime.secret.key"
VAULT_FILE_NAME = "agent_runtime.secrets.json"
ALGORITHM = "HMAC-SHA256-STREAM"


class SecretStoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _vault_file(state_file: Path) -> Path:
    configured = os.getenv("AGENT_RUNTIME_SECRET_VAULT_FILE", "").strip()
    if configured:
        return Path(configured)
    return state_file.with_name(VAULT_FILE_NAME)


def _key_file(state_file: Path) -> Path:
    configured = os.getenv("AGENT_RUNTIME_SECRET_KEY_FILE", "").strip()
    if configured:
        return Path(configured)
    return state_file.with_name(KEY_FILE_NAME)


def _read_or_create_key_file(state_file: Path) -> str:
    key_path = _key_file(state_file)
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_material = secrets.token_urlsafe(48)
    key_path.write_text(key_material, encoding="utf-8")
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return key_material


def _hash_key(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _key_material(state_file: Path) -> tuple[bytes, str]:
    for env_name in SECRET_KEY_ENV_NAMES:
        value = os.getenv(env_name, "").strip()
        if value:
            return _hash_key(value), f"ENV:{env_name}"

    local_key = _read_or_create_key_file(state_file)
    return _hash_key(local_key), "LOCAL_KEY_FILE"


def _previous_key_materials() -> list[tuple[bytes, str]]:
    materials: list[tuple[bytes, str]] = []
    for env_name in PREVIOUS_SECRET_KEY_ENV_NAMES:
        value = os.getenv(env_name, "").strip()
        if value:
            materials.append((_hash_key(value), f"PREVIOUS_ENV:{env_name}"))
    return materials


def _derive_key(master_key: bytes, purpose: bytes) -> bytes:
    return hmac.new(master_key, purpose, hashlib.sha256).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        counter_bytes = counter.to_bytes(8, "big")
        output.extend(hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return bytes(output[:length])


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _seal_value_with_key(value: str, master_key: bytes, key_source: str) -> Dict[str, Any]:
    encryption_key = _derive_key(master_key, b"agent-runtime-secret-encryption-v1")
    signing_key = _derive_key(master_key, b"agent-runtime-secret-signing-v1")
    plaintext = value.encode("utf-8")
    nonce = secrets.token_bytes(16)
    ciphertext = _xor(plaintext, _keystream(encryption_key, nonce, len(plaintext)))
    tag = hmac.new(signing_key, b"v1" + nonce + ciphertext, hashlib.sha256).digest()
    return {
        "alg": ALGORITHM,
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
        "tag": _b64encode(tag),
        "key_source": key_source,
        "updated_at": _now(),
    }


def _seal_value(value: str, state_file: Path) -> Dict[str, Any]:
    master_key, key_source = _key_material(state_file)
    return _seal_value_with_key(value, master_key, key_source)


def _open_value_with_key(envelope: Dict[str, Any], master_key: bytes) -> str:
    encryption_key = _derive_key(master_key, b"agent-runtime-secret-encryption-v1")
    signing_key = _derive_key(master_key, b"agent-runtime-secret-signing-v1")
    nonce = _b64decode(str(envelope["nonce"]))
    ciphertext = _b64decode(str(envelope["ciphertext"]))
    tag = _b64decode(str(envelope["tag"]))
    expected = hmac.new(signing_key, b"v1" + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise SecretStoreError("Secret authentication failed.")
    plaintext = _xor(ciphertext, _keystream(encryption_key, nonce, len(ciphertext)))
    return plaintext.decode("utf-8")


def _open_value(envelope: Dict[str, Any], state_file: Path) -> str:
    if envelope.get("alg") != ALGORITHM:
        raise SecretStoreError(f"Unsupported secret algorithm: {envelope.get('alg')}")

    candidates = [_key_material(state_file), *_previous_key_materials()]
    errors = []
    for master_key, _ in candidates:
        try:
            return _open_value_with_key(envelope, master_key)
        except SecretStoreError as exc:
            errors.append(str(exc))
    raise SecretStoreError(
        "Secret authentication failed. Check AGENT_RUNTIME_SECRET_KEY, "
        "AGENT_RUNTIME_SECRET_KEY_PREVIOUS, or the local key file."
    ) from None


def _load_vault(state_file: Path) -> Dict[str, Any]:
    vault_path = _vault_file(state_file)
    if not vault_path.exists():
        return {"version": 1, "secrets": {}, "updated_at": _now()}
    with vault_path.open("r", encoding="utf-8") as file:
        vault = json.load(file)
    vault.setdefault("version", 1)
    vault.setdefault("secrets", {})
    return vault


def _save_vault(state_file: Path, vault: Dict[str, Any]) -> None:
    vault_path = _vault_file(state_file)
    vault_path.parent.mkdir(parents=True, exist_ok=True)
    vault["updated_at"] = _now()
    temp_path = vault_path.with_name(f"{vault_path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(vault, file, indent=2, ensure_ascii=False)
        _replace_vault_file(temp_path, vault_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    try:
        vault_path.chmod(0o600)
    except OSError:
        pass


def _replace_vault_file(temp_path: Path, vault_path: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(temp_path, vault_path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def make_secret_ref(scope: str, item_id: str, field: str) -> str:
    return f"{SECRET_REF_PREFIX}{scope}:{item_id}:{field}"


def make_secret_version_ref(ref: str) -> str:
    base_ref = str(ref).split(":version:", 1)[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{base_ref}:version:{timestamp}_{secrets.token_hex(4)}"


def store_runtime_secret(state_file: Path, scope: str, item_id: str, field: str, value: str) -> str:
    ref = make_secret_ref(scope, item_id, field)
    vault = _load_vault(state_file)
    vault.setdefault("secrets", {})[ref] = _seal_value(value, state_file)
    _save_vault(state_file, vault)
    return ref


def store_runtime_secret_version(state_file: Path, ref: str, value: str) -> str:
    if not ref or not str(ref).startswith(SECRET_REF_PREFIX):
        raise ValueError("Invalid runtime secret reference.")
    version_ref = make_secret_version_ref(ref)
    vault = _load_vault(state_file)
    vault.setdefault("secrets", {})[version_ref] = _seal_value(value, state_file)
    _save_vault(state_file, vault)
    return version_ref


def load_runtime_secret(state_file: Path, ref: str) -> Optional[str]:
    if not ref or not str(ref).startswith(SECRET_REF_PREFIX):
        return None
    vault = _load_vault(state_file)
    envelope = vault.get("secrets", {}).get(ref)
    if not envelope:
        return None
    return _open_value(envelope, state_file)


def delete_runtime_secret(state_file: Path, ref: str) -> None:
    if not ref:
        return
    vault = _load_vault(state_file)
    if ref in vault.get("secrets", {}):
        del vault["secrets"][ref]
        _save_vault(state_file, vault)


def runtime_secret_storage_status(state_file: Path) -> Dict[str, Any]:
    _, key_source = _key_material(state_file)
    vault_path = _vault_file(state_file)
    key_path = _key_file(state_file)
    return {
        "version": 1,
        "mode": "ENCRYPTED_AT_REST",
        "algorithm": ALGORITHM,
        "key_source": key_source,
        "vault_file": str(vault_path),
        "vault_exists": vault_path.exists(),
        "local_key_file_exists": key_path.exists(),
        "plaintext_in_runtime_config": False,
    }


def rotate_runtime_secret_vault(state_file: Path) -> Dict[str, Any]:
    """Re-encrypt every secret with the current key source.

    Production rotation:
    1. Set AGENT_RUNTIME_SECRET_KEY to the new key.
    2. Set AGENT_RUNTIME_SECRET_KEY_PREVIOUS to the old key for this command only.
    3. Run the rotation command, then remove AGENT_RUNTIME_SECRET_KEY_PREVIOUS.

    Local development without env keys rotates the generated local key file.
    """
    vault = _load_vault(state_file)
    encrypted = vault.get("secrets", {})
    current_values: Dict[str, str] = {}
    for ref, envelope in encrypted.items():
        current_values[ref] = _open_value(envelope, state_file)

    env_key_configured = any(os.getenv(name, "").strip() for name in SECRET_KEY_ENV_NAMES)
    if env_key_configured:
        master_key, key_source = _key_material(state_file)
    else:
        key_path = _key_file(state_file)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_material = secrets.token_urlsafe(48)
        key_path.write_text(key_material, encoding="utf-8")
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        master_key = _hash_key(key_material)
        key_source = "LOCAL_KEY_FILE_ROTATED"

    vault["secrets"] = {
        ref: _seal_value_with_key(value, master_key, key_source)
        for ref, value in current_values.items()
    }
    vault["last_rotation_at"] = _now()
    vault["last_rotation_key_source"] = key_source
    _save_vault(state_file, vault)
    return {
        "rotated": True,
        "secret_count": len(current_values),
        "key_source": key_source,
        "vault_file": str(_vault_file(state_file)),
        "rotated_at": vault["last_rotation_at"],
    }


def verify_runtime_secret_vault(state_file: Path) -> Dict[str, Any]:
    vault = _load_vault(state_file)
    failures = []
    for ref, envelope in vault.get("secrets", {}).items():
        try:
            _open_value(envelope, state_file)
        except Exception as exc:
            failures.append({"ref": ref, "error": str(exc)})
    return {
        "ok": not failures,
        "secret_count": len(vault.get("secrets", {})),
        "failures": failures,
        "vault_file": str(_vault_file(state_file)),
    }
