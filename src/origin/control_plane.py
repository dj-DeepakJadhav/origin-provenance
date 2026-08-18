"""CockroachDB Cloud Control Plane & Cluster Topology Interface.

Surfaces runtime control plane state by combining:
1. Direct ccloud CLI JSON output (`ccloud cluster list --output json`) when configured.
2. Direct CockroachDB cluster control & zone configuration queries (`SHOW ZONE CONFIGURATION`,
   `SHOW RANGES`, `gateway_region()`).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any

from . import db

log = logging.getLogger(__name__)


def inspect_cluster_control_plane() -> dict[str, Any]:
    """Query CockroachDB Cloud control plane and live database topology."""
    control_info: dict[str, Any] = {
        "ccloud_available": False,
        "source": "sql_control_plane",
        "cluster_info": {},
        "zones": {},
    }

    # 1. ccloud CLI, if this host has one.
    #
    # `shutil.which` alone is not enough: ccloud is deliberately installed to
    # %APPDATA%\ccloud and *not* added to PATH, to keep the machine-wide footprint
    # contained. CCLOUD_BIN names it explicitly for that case. Without this the
    # lookup silently fails and the response reports the SQL fallback, which reads
    # like the CLI is absent rather than merely unlisted.
    ccloud_bin = os.getenv("CCLOUD_BIN") or shutil.which("ccloud")
    if ccloud_bin and not os.path.exists(ccloud_bin):
        log.warning("CCLOUD_BIN points at %s, which does not exist", ccloud_bin)
        ccloud_bin = None

    if ccloud_bin:
        try:
            res = subprocess.run(
                [ccloud_bin, "cluster", "list", "--output", "json"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                control_info["ccloud_available"] = True
                control_info["source"] = "ccloud_cli"
                control_info["ccloud_clusters"] = json.loads(res.stdout)
            else:
                # Almost always an unauthenticated CLI. Reported rather than
                # swallowed: "the binary is here but not logged in" and "there is
                # no binary" need different fixes, and a bare False conflates them.
                control_info["ccloud_error"] = (
                    (res.stderr or res.stdout or "").strip()[:200]
                    or f"ccloud exited {res.returncode} with no output"
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("ccloud CLI execution failed: %s", exc)
            control_info["ccloud_error"] = f"{type(exc).__name__}: {exc}"[:200]

    # 2. Query live database zone configurations and gateway region
    with db.connect() as conn, conn.cursor() as cur:
        # Version and gateway region
        cur.execute("SELECT version() AS v, current_database() AS db")
        row = cur.fetchone()
        control_info["cluster_info"]["database"] = row["db"]
        control_info["cluster_info"]["version"] = row["v"].split(",")[0]

        try:
            cur.execute("SELECT gateway_region() AS region")
            reg = cur.fetchone()
            control_info["cluster_info"]["gateway_region"] = reg["region"] if reg else "unknown"
        except Exception:  # noqa: BLE001
            control_info["cluster_info"]["gateway_region"] = "default"

        # Zone configuration for tables (e.g. gc.ttlseconds)
        try:
            cur.execute("SHOW ZONE CONFIGURATION FOR TABLE session_turns")
            zone_row = cur.fetchone()
            if zone_row:
                control_info["zones"]["session_turns"] = zone_row.get("config_sql") or str(zone_row)
        except Exception as exc:  # noqa: BLE001
            control_info["zones"]["session_turns"] = f"default ({exc})"

        # Vector table range distribution
        try:
            cur.execute("SHOW RANGES FROM TABLE session_turns")
            ranges = cur.fetchall()
            control_info["cluster_info"]["session_turns_ranges_count"] = len(ranges)
        except Exception:  # noqa: BLE001
            control_info["cluster_info"]["session_turns_ranges_count"] = 1

    return control_info
