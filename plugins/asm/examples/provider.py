#!/usr/bin/env python3
"""Synthetic provider CLI. Only run through ASM: issue intentionally emits a token."""
import json
import os
from pathlib import Path
import secrets
import sys


def main():
    if sys.argv[1:] == ["issue"]:
        token = secrets.token_urlsafe(32)
        with Path("issued.json").open("x") as file:
            os.chmod(file.name, 0o600)
            json.dump({"access_token": token}, file)
        # A real issuing CLI may print credentials. ASM captures this pipe.
        print(json.dumps({"access_token": token}))
    elif sys.argv[1:] == ["verify"]:
        expected = json.loads(Path("issued.json").read_text())["access_token"]
        if os.environ.get("SERVICE_TOKEN") != expected:
            raise ValueError("authentication_failed")
    else:
        raise ValueError("unknown_example_command")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"error":"example_provider_failed"}', file=sys.stderr)
        sys.exit(1)
