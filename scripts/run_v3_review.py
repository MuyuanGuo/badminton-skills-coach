#!/usr/bin/env python3
"""Run the local-only v3 evidence review workbench."""

import argparse
import json
from pathlib import Path

from v3.review_server import ReviewApplication, create_server


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / ".local/v3/review/vertical-slice-session.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    session = json.loads(args.session.read_text(encoding="utf-8"))
    media_path = Path(session["media_path"])
    application = ReviewApplication(
        candidate_path=Path(session["candidate_path"]),
        ledger_path=Path(session["ledger_path"]),
        media_path=media_path,
        media_root=media_path.parent,
    )
    server = create_server(application, args.host, args.port)
    actual_port = server.server_address[1]
    url = f"http://{args.host}:{actual_port}/?token={application.session_token}"
    print(f"v3 evidence review workbench: {url}", flush=True)
    print("Private local session; candidates are not approved evidence.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
