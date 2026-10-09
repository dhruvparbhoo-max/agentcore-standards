"""Make the local signing key for ``make local`` and mint a test token for the front door.

    uv run python scripts/local_token.py --init           # key pair under build/local (outside git)
    uv run python scripts/local_token.py --sub alice      # prints a bearer token

The front door container trusts only this key's public half, and only when
``FRONT_DOOR_LOCAL_PUBLIC_KEY_FILE`` is set. A deploy never sets it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agentcore_front_door.local import mint, write_key_pair

FOLDER = Path(__file__).resolve().parents[1] / "build" / "local"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--sub", default="local-user")
    parser.add_argument("--team", default="platform")
    parser.add_argument("--tenant", default="local")
    args = parser.parse_args()
    private, public = write_key_pair(FOLDER)
    if args.init:
        print(public)
        return 0
    print(mint(private, {"sub": args.sub, "custom:team": args.team, "custom:tenant": args.tenant}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
