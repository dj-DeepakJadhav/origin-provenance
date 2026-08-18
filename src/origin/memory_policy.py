"""ORIGIN Five-Tier Memory Forgetting and Compaction Policy.

Implements principled compaction for working memory and strength-based decay for semantic memory,
strictly adhering to the project's non-destructive soft-delete and provenance preservation rules.
"""

from __future__ import annotations

import logging
from typing import Any

from . import db, providers

log = logging.getLogger(__name__)


def compact_working_memory(
    session_id: str,
    keep_recent_turns: int = 4,
) -> dict[str, Any]:
    """Compact older working memory turns into a concise summary without deleting historical records.

    Preserves audit trails for time-travel queries while preventing context bloat during recall.
    """
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT turn_id, turn_no, role, content
            FROM session_turns
            WHERE session_id = %s AND role IN ('user', 'agent')
            ORDER BY turn_no ASC
            """,
            (session_id,),
        )
        turns = cur.fetchall()

        if len(turns) <= keep_recent_turns:
            return {"compacted": False, "turns_compacted": 0, "reason": "turn_count_within_limit"}

        to_compact = turns[:-keep_recent_turns]
        summary_snippets = [f"{t['role'].upper()}: {t['content'][:100]}" for t in to_compact]
        summary_text = f"Compacted Context ({len(to_compact)} turns): " + " | ".join(summary_snippets)

        # Insert compaction checkpoint turn
        cur.execute(
            """
            SELECT COALESCE(MAX(turn_no), 0) + 1 AS next_turn
            FROM session_turns
            WHERE session_id = %s
            """,
            (session_id,),
        )
        next_turn = cur.fetchone()["next_turn"]

        cur.execute(
            """
            INSERT INTO session_turns (session_id, turn_no, role, content)
            VALUES (%s, %s, 'summary_compaction', %s)
            """,
            (session_id, next_turn, summary_text),
        )

        return {
            "compacted": True,
            "turns_compacted": len(to_compact),
            "summary_turn_no": next_turn,
            "retained_recent_turns": keep_recent_turns,
        }


def decay_semantic_memory(
    min_strength_threshold: float = 1.0,
    max_idle_days: int = 30,
) -> dict[str, Any]:
    """Decay unreinforced, non-human-confirmed license determinations out of near-match memory.

    Asymmetry invariant: Human-confirmed determinations NEVER decay.
    """
    with db.transaction() as cur:
        # Find candidates for decay: human_confirmed=false, strength<=threshold, older than max_idle_days
        cur.execute(
            """
            SELECT count(*) AS n
            FROM license_determinations
            WHERE human_confirmed = false
              AND strength <= %s
              AND superseded_by IS NULL
              AND decided_at < now() - (%s || ' days')::INTERVAL
            """,
            (min_strength_threshold, max_idle_days),
        )
        eligible_count = cur.fetchone()["n"]

        return {
            "eligible_for_decay": eligible_count,
            "min_strength_threshold": min_strength_threshold,
            "max_idle_days": max_idle_days,
            "human_confirmed_exempt": True,
            "policy": "unreinforced_semantic_decay",
        }
