import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the local FastAPI dev server.")
    parser.add_argument(
        "--host",
        default=os.environ.get("BACKEND_HOST", "127.0.0.1"),
        help="Host address to bind. Defaults to BACKEND_HOST or 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BACKEND_PORT", "8000")),
        help="Port to bind. Defaults to BACKEND_PORT or 8000.",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable the uvicorn file watcher. Useful for smoke checks.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=not args.no_reload)
