import argparse
import json

from .core.agent_runtime_store import STORAGE_FILE, _load_state
from .core.secret_store import (
    rotate_runtime_secret_vault,
    runtime_secret_storage_status,
    verify_runtime_secret_vault,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Agent Runtime secret vault.")
    parser.add_argument(
        "command",
        choices=("status", "verify", "rotate"),
        help="status shows storage metadata; verify decrypts every secret; rotate re-encrypts with the current key source.",
    )
    args = parser.parse_args()

    if args.command == "status":
        state = _load_state()
        payload = {
            "storage": runtime_secret_storage_status(STORAGE_FILE),
            "secret_ref_sections": sorted((state.get("secret_refs") or {}).keys()),
        }
    elif args.command == "verify":
        _load_state()
        payload = verify_runtime_secret_vault(STORAGE_FILE)
    else:
        _load_state()
        payload = rotate_runtime_secret_vault(STORAGE_FILE)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
