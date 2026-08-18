"""Generate the Lambda environment file from ``.env``, without hand-editing.

Hand-copying ``DATABASE_URL`` into JSON failed twice during the first deploy, in
two different ways, and neither failure was obvious from the error:

* Pasting from the CockroachDB Cloud console dragged in the trailing "Sql user"
  block, putting a newline inside the string. The AWS CLI reported
  ``Invalid control character`` and applied **no** environment at all — so the
  next invoke failed on a missing ``DATABASE_URL`` rather than on the paste.
* A later paste carried a superseded password, which surfaced only as
  ``password authentication failed for user dj`` from inside the running
  function.

Deriving the value from the ``.env`` that is already known to work removes both.

The output goes **outside the repository** (``%USERPROFILE%`` / ``$HOME``) because
it contains the cluster password. ``.gitignore`` also blocks ``*env*.json`` as a
backstop, but the file should never be in the tree to begin with.

Usage::

    python deploy/make-lambda-env.py
    aws lambda update-function-configuration --function-name origin-api \
        --region eu-central-1 --environment file://%USERPROFILE%/origin-lambda-env.json

``ORIGIN_WRITE_TOKEN`` is deliberately a fixed, publishable demo value rather
than a secret: the endpoint must be exercisable by judges, and an empty token
would leave ``POST /api/v1/takedown`` open to the internet (``app.py:67`` only
gates when the value is non-empty).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

#: Published in the README and on Devpost so judges can exercise the write path.
DEMO_WRITE_TOKEN = "origin-demo-2026"

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT_NAME = "origin-lambda-env.json"

#: Reserved by Lambda — setting any of these makes UpdateFunctionConfiguration
#: fail outright. The region is injected automatically and credentials come from
#: the execution role, so S3 works without them.
RESERVED = frozenset(
    {
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
)


def read_dotenv(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def main() -> int:
    dotenv = REPO_ROOT / ".env"
    if not dotenv.exists():
        print(f"error: {dotenv} not found; copy .env.example and fill it in")
        return 1

    env = read_dotenv(dotenv)
    database_url = env.get("DATABASE_URL", "")

    if not database_url:
        print("error: DATABASE_URL is not set in .env")
        return 1
    # The failure this script exists to prevent. Checked rather than trusted.
    if any(c in database_url for c in "\r\n\t"):
        print("error: DATABASE_URL contains a line break or tab.")
        print("       It must be a single line. Re-copy just the connection URI.")
        return 1

    variables = {
        "DATABASE_URL": database_url,
        "ORIGIN_STORAGE": "s3",
        "ORIGIN_S3_BUCKET": env.get(
            "ORIGIN_S3_BUCKET", "origin-provenance-248557779236"
        ),
        "ORIGIN_S3_PREFIX": env.get("ORIGIN_S3_PREFIX", "origin/documents"),
        # Bedrock is blocked at account level, so the deployed profile classifies
        # novel licences with the rule-based path rather than a model.
        "ORIGIN_PROVIDER": "local",
        "ORIGIN_EMBED_DIM": env.get("ORIGIN_EMBED_DIM", "1024"),
        "ORIGIN_WRITE_TOKEN": DEMO_WRITE_TOKEN,
    }

    leaked = RESERVED & set(variables)
    if leaked:  # pragma: no cover - guards against future edits to this file
        print(f"error: refusing to emit Lambda-reserved keys: {sorted(leaked)}")
        return 1

    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        print("error: neither USERPROFILE nor HOME is set")
        return 1

    out = pathlib.Path(home) / OUTPUT_NAME
    out.write_text(json.dumps({"Variables": variables}, indent=2), encoding="utf-8")

    # Never print the URL itself — this output gets pasted into chats and issues.
    host = database_url.split("@")[-1].split(":")[0] if "@" in database_url else "?"
    print(f"wrote {out}")
    print(f"  keys    : {len(variables)} ({', '.join(sorted(variables))})")
    print(f"  cluster : {host}")
    print("  password: taken from .env (not printed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
