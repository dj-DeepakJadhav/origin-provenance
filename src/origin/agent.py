"""Agent execution loop with explicit, verifiable memory reads.

Five persistent memory types are surfaced on CockroachDB:
1. **Working Memory**: Conversational state (`sessions`, `session_turns`) with recency and vector recall over turn history.
2. **Semantic Memory**: Reusable license determinations (`license_determinations`) reinforced on reuse and corrected without overwriting.
3. **Episodic Memory**: Past recorded answers (`answers`, `answer_attributions`) and their receipts.
4. **Temporal Memory**: Dataset state at specific points in time via MVCC `AS OF SYSTEM TIME` and bitemporal ranges.
5. **Task State Memory**: Multi-step agent task progression (`agent_tasks`) with step-level persistence and crash resumption.

Crucially, user turns, agent turns, generated answers, and document attributions
commit **atomically in one database transaction**.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import corpus, db, ledger, memory_policy, retrieval
from .providers import Provider, get_provider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryTrace:
    working_turns_recalled: int
    semantic_rulings_used: int
    episodic_answers_used: int
    memory_enabled: bool
    attributions_recorded: int
    model_invoked: bool
    acted_on: str
    details: dict[str, Any]


def create_session(corpus_id: str, actor: str | None = None) -> str:
    """Create a new conversational session linked to a corpus."""
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO sessions (corpus_id, actor)
            VALUES (%s, %s)
            RETURNING session_id
            """,
            (corpus_id, actor),
        )
        row = cur.fetchone()
        return str(row["session_id"])


def recall_working(
    session_id: str,
    query_vector: list[float] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve recent conversation turns for a session.

    Combines recency (last N turns) with semantic vector recall over earlier turns
    if a query vector is provided.
    """
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT turn_id, session_id, turn_no, role, content, answer_id, created_at
            FROM session_turns
            WHERE session_id = %s
            ORDER BY turn_no DESC
            LIMIT %s
            """,
            (session_id, limit),
        )
        recent = [dict(row) for row in cur.fetchall()]
        recent.reverse()

    if not query_vector:
        return recent

    # Vector search for relevant turns in this session
    v_literal = db.vector_literal(query_vector)
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT turn_id, session_id, turn_no, role, content, answer_id, created_at,
                   embedding <=> %s::VECTOR AS distance
            FROM session_turns
            WHERE session_id = %s AND embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT %s
            """,
            (v_literal, session_id, limit),
        )
        similar = [dict(row) for row in cur.fetchall()]

    # Deduplicate recent + similar by turn_id
    seen = set()
    combined = []
    for turn in recent + similar:
        tid = turn["turn_id"]
        if tid not in seen:
            seen.add(tid)
            combined.append(turn)

    combined.sort(key=lambda x: x["turn_no"])
    return combined


def recall_semantic(raw_license: str, provider: Provider | None = None) -> dict[str, Any] | None:
    """Recall a learned/reinforced license determination from semantic memory.

    Checks exact match first; if absent, falls back to cosine vector similarity
    over license_determinations within REUSE_DISTANCE_THRESHOLD.
    """
    cleaned = raw_license.strip()
    # 1. Exact string match (case-insensitive)
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT determination_id, license_raw, determined_class,
                   rationale, strength, decided_by, decided_at, superseded_by
            FROM license_determinations
            WHERE (license_raw = %s OR license_raw ILIKE %s) AND superseded_by IS NULL
            ORDER BY human_confirmed DESC, strength DESC
            LIMIT 1
            """,
            (cleaned, cleaned),
        )
        row = cur.fetchone()
        if row:
            res = dict(row)
            res["match_type"] = "exact"
            return res

    # 2. Vector near-match fallback (decay unreinforced non-human rulings > 30 days)
    active_provider = provider or get_provider()
    vec = active_provider.embed(raw_license)
    v_literal = db.vector_literal(vec)

    with db.transaction() as cur:
        cur.execute(
            """
            SELECT determination_id, license_raw, determined_class,
                   rationale, strength, decided_by, decided_at, superseded_by,
                   embedding <=> %s::VECTOR AS distance
            FROM license_determinations
            WHERE superseded_by IS NULL 
              AND embedding IS NOT NULL
              AND (human_confirmed = true OR strength > 0.5 OR decided_at > now() - INTERVAL '30 days')
            ORDER BY distance ASC
            LIMIT 1
            """,
            (v_literal,),
        )
        near = cur.fetchone()
        if near and float(near["distance"]) <= ledger.REUSE_DISTANCE_THRESHOLD:
            res = dict(near)
            res["match_type"] = "similar"
            res["similarity"] = 1.0 - float(near["distance"])
            return res

    return None


def recall_episodic(
    question: str,
    query_vector: list[float] | None = None,
    limit: int = 3,
    provider: Provider | None = None,
) -> list[dict[str, Any]]:
    """Recall prior recorded answers and their receipts from episodic memory."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT a.answer_id, a.corpus_id, a.question, a.answer_text,
                   a.model_version, a.asked_at, a.asked_by
            FROM answers a
            ORDER BY a.asked_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        answer_rows = cur.fetchall()

    results: list[dict[str, Any]] = []
    with db.transaction() as cur:
        for a in answer_rows:
            aid = a["answer_id"]
            cur.execute(
                """
                SELECT att.rank, att.similarity, d.doc_id, d.title, d.license_class
                FROM answer_attributions att
                JOIN documents d ON d.doc_id = att.doc_id
                WHERE att.answer_id = %s
                ORDER BY att.rank
                """,
                (aid,),
            )
            receipts = [dict(r) for r in cur.fetchall()]
            results.append({
                "answer_id": str(aid),
                "corpus_id": str(a["corpus_id"]),
                "question": a["question"],
                "answer_text": a["answer_text"],
                "model_version": a["model_version"],
                "asked_at": a["asked_at"],
                "asked_by": a["asked_by"],
                "receipts": receipts,
            })

    return results


def recall_temporal(corpus_id: str, when: datetime | str) -> dict[str, Any]:
    """Recall corpus state at a past point-in-time via MVCC or bitemporal path."""
    membership = corpus.membership_as_of(corpus_id, when, prefer_mvcc=True)
    return {
        "corpus_id": corpus_id,
        "as_of": str(when),
        "source": membership.source,
        "member_count": len(membership.doc_ids),
        "doc_ids": sorted(list(membership.doc_ids)),
    }


def get_session_transcript(session_id: str) -> dict[str, Any]:
    """Retrieve full transcript and session metadata."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT session_id, corpus_id, started_at, last_seen_at, actor
            FROM sessions
            WHERE session_id = %s
            """,
            (session_id,),
        )
        session_row = cur.fetchone()
        if not session_row:
            raise KeyError(f"Session {session_id} not found")

        cur.execute(
            """
            SELECT turn_id, turn_no, role, content, answer_id, created_at
            FROM session_turns
            WHERE session_id = %s
            ORDER BY turn_no ASC
            """,
            (session_id,),
        )
        turns = [dict(row) for row in cur.fetchall()]

    return {
        "session": dict(session_row),
        "turns": turns,
    }


def respond(
    session_id: str,
    question: str,
    *,
    provider: Provider | None = None,
    asked_by: str | None = None,
    memory_enabled: bool = True,
) -> dict[str, Any]:
    """Agent loop: recall memory, resolve follow-ons, retrieve, answer, and commit atomically.

    When memory_enabled is False, skips working/semantic/episodic recall to allow
    strict ablation benchmarking while keeping retrieval and atomic transactions identical.
    """
    active_provider = provider or get_provider()
    question_vector = active_provider.embed(question)

    # 1. Fetch session details (read-only query)
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT session_id, corpus_id, actor
            FROM sessions
            WHERE session_id = %s
            """,
            (session_id,),
        )
        session_row = cur.fetchone()
        if not session_row:
            raise KeyError(f"Session {session_id} not found")
        corpus_id = str(session_row["corpus_id"])

    # 2. Recall working memory (if enabled)
    working_turns = recall_working(session_id, question_vector, limit=4) if memory_enabled else []

    # Contextualize follow-up questions using prior turns if working memory is present
    contextualized_question = question
    if memory_enabled and working_turns and len(question.split()) < 10:
        last_turn = working_turns[-1]
        if last_turn["role"] == "agent":
            contextualized_question = f"{question} (Context: {last_turn['content'][:200]})"

    # 3. Recall episodic memory (if enabled)
    episodic_past = recall_episodic(question, limit=2, provider=active_provider) if memory_enabled else []

    # 4. Prepare answer (read-only retrieval + generation, NO database writes)
    text, hits, model_version, extractive, unembedded = retrieval.prepare_answer(
        corpus_id=corpus_id,
        question=contextualized_question,
        top_k=4,
        provider=active_provider,
    )

    # 5. Pre-compute vector embeddings for session turns outside transaction
    user_vec_literal = db.vector_literal(question_vector)
    agent_ans_vec = active_provider.embed(text)
    agent_vec_literal = db.vector_literal(agent_ans_vec)

    # 6. ATOMIC WRITE: Record answer + attributions + user turn + agent turn in ONE transaction with retry
    def _write_atomic_turn(cur) -> tuple[str, int]:
        # A. Record answer + document attributions
        ans_id = corpus.record_answer_tx(
            cur,
            corpus_id=corpus_id,
            question=contextualized_question,
            answer_text=text,
            retrieved=[(h.doc_id, h.similarity) for h in hits],
            model_version=model_version,
            asked_by=asked_by or session_row["actor"],
        )

        # B. Get next turn_no
        cur.execute(
            """
            SELECT COALESCE(MAX(turn_no), 0) + 1 AS next_turn
            FROM session_turns
            WHERE session_id = %s
            """,
            (session_id,),
        )
        u_turn_no = cur.fetchone()["next_turn"]
        a_turn_no = u_turn_no + 1

        # C. Insert user turn
        cur.execute(
            """
            INSERT INTO session_turns (session_id, turn_no, role, content, embedding)
            VALUES (%s, %s, %s, %s, %s::VECTOR)
            """,
            (session_id, u_turn_no, "user", question, user_vec_literal),
        )

        # D. Insert agent turn linked to answer_id
        cur.execute(
            """
            INSERT INTO session_turns (session_id, turn_no, role, content, answer_id, embedding)
            VALUES (%s, %s, %s, %s, %s, %s::VECTOR)
            """,
            (session_id, a_turn_no, "agent", text, ans_id, agent_vec_literal),
        )

        # E. Update session last_seen_at
        cur.execute(
            """
            UPDATE sessions
            SET last_seen_at = now()
            WHERE session_id = %s
            """,
            (session_id,),
        )
        return ans_id, a_turn_no

    answer_id, agent_turn_no = db.run_in_transaction(_write_atomic_turn)

    # 6b. Apply working memory compaction policy if turns exceed threshold
    if memory_enabled and agent_turn_no > 6:
        try:
            memory_policy.compact_working_memory(session_id, keep_recent_turns=4)
        except Exception as exc:
            log.warning("Memory compaction deferred (%s)", exc)

    # 7. Check semantic memory used for retrieved documents (if enabled)
    semantic_rulings_count = 0
    if memory_enabled:
        for h in hits:
            if h.license_raw:
                sem = recall_semantic(h.license_raw, provider=active_provider)
                if sem:
                    semantic_rulings_count += 1

    if memory_enabled:
        acted_on_msg = (
            f"Grounded response in {len(hits)} retrieved documents; "
            f"recalled {len(working_turns)} working-memory turns and {semantic_rulings_count} remembered license rulings. "
            f"Committed turn, answer, and {len(hits)} attributions in one atomic transaction."
        )
    else:
        acted_on_msg = (
            f"Ablation mode (memory disabled): Grounded response in {len(hits)} retrieved documents. "
            f"Committed turn, answer, and {len(hits)} attributions in one atomic transaction."
        )

    memory_trace = MemoryTrace(
        working_turns_recalled=len(working_turns),
        semantic_rulings_used=semantic_rulings_count,
        episodic_answers_used=len(episodic_past),
        memory_enabled=memory_enabled,
        attributions_recorded=len(hits),
        model_invoked=not extractive,
        acted_on=acted_on_msg,
        details={
            "working_memory": [
                {"turn_no": t["turn_no"], "role": t["role"], "snippet": t["content"][:60]}
                for t in working_turns
            ],
            "retrieved_hits": len(hits),
            "unembedded_members": unembedded,
            "episodic_past_count": len(episodic_past),
            "memory_enabled": memory_enabled,
        },
    )

    return {
        "session_id": session_id,
        "turn_no": agent_turn_no,
        "question": question,
        "answer_id": answer_id,
        "text": text,
        "model_version": model_version,
        "extractive": extractive,
        "hits": [
            {
                "doc_id": h.doc_id,
                "title": h.title,
                "license_class": h.license_class,
                "similarity": h.similarity,
                "snippet": h.snippet,
            }
            for h in hits
        ],
        "memory_used": {
            "working_turns_recalled": memory_trace.working_turns_recalled,
            "semantic_rulings_used": memory_trace.semantic_rulings_used,
            "episodic_answers_used": memory_trace.episodic_answers_used,
            "memory_enabled": memory_trace.memory_enabled,
            "attributions_recorded": memory_trace.attributions_recorded,
            "model_invoked": memory_trace.model_invoked,
            "acted_on": memory_trace.acted_on,
            "trace": memory_trace.details,
        },
    }


# --------------------------------------------------------------------------
# Task State Memory & Resumable Execution
# --------------------------------------------------------------------------

def create_task(
    session_id: str,
    kind: str,
    total_steps: int = 4,
    payload: dict[str, Any] | None = None,
) -> str:
    """Create a new agent task with persistent state in CockroachDB."""
    import json
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO agent_tasks (session_id, kind, state, step_no, total_steps, payload)
            VALUES (%s, %s, 'pending', 0, %s, %s)
            RETURNING task_id
            """,
            (session_id, kind, total_steps, json.dumps(payload or {})),
        )
        row = cur.fetchone()
        return str(row["task_id"])


def update_task_state(
    task_id: str,
    *,
    state: str,
    step_no: int,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the current step and execution state for a task."""
    import json
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE agent_tasks
            SET state = %s,
                step_no = %s,
                payload = COALESCE(%s, payload),
                result = COALESCE(%s, result),
                updated_at = now()
            WHERE task_id = %s
            RETURNING task_id, session_id, kind, state, step_no, total_steps, payload, result, created_at, updated_at
            """,
            (
                state,
                step_no,
                json.dumps(payload) if payload is not None else None,
                json.dumps(result) if result is not None else None,
                task_id,
            ),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Task {task_id} not found")
        return dict(row)


def get_task(task_id: str) -> dict[str, Any]:
    """Retrieve full task state."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT task_id, session_id, kind, state, step_no, total_steps, payload, result, created_at, updated_at
            FROM agent_tasks
            WHERE task_id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Task {task_id} not found")
        return dict(row)


def list_tasks(session_id: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
    """List tasks, optionally filtered by session_id or state."""
    query = "SELECT task_id, session_id, kind, state, step_no, total_steps, payload, result, created_at, updated_at FROM agent_tasks WHERE 1=1"
    params: list[Any] = []
    if session_id:
        query += " AND session_id = %s"
        params.append(session_id)
    if state:
        query += " AND state = %s"
        params.append(state)
    query += " ORDER BY created_at DESC"

    with db.transaction() as cur:
        cur.execute(query, tuple(params))
        return [dict(row) for row in cur.fetchall()]


def run_corpus_audit_task(
    session_id: str,
    corpus_id: str,
    *,
    task_id: str | None = None,
    simulate_crash_at_step: int | None = None,
) -> dict[str, Any]:
    """Multi-step agentic task: inspect, gate, verify integrity, and report.

    Persists task state at every step boundary. If interrupted or crashed,
    resumes from the last completed step when called with task_id.
    """
    from datetime import datetime, timezone
    from . import gate

    if not task_id:
        task_id = create_task(session_id, kind="corpus_audit", total_steps=4, payload={"corpus_id": corpus_id})

    task = get_task(task_id)
    current_step = task["step_no"]
    accumulated_result = task["result"] or {}

    # Step 1: Member inspection
    if current_step < 1:
        if simulate_crash_at_step == 1:
            update_task_state(task_id, state="blocked", step_no=0, result=accumulated_result)
            raise RuntimeError("SIMULATED AGENT CRASH AT STEP 1 (MEMBER INSPECTION)")
        with db.transaction() as cur:
            cur.execute(
                "SELECT count(*) as count FROM corpus_members WHERE corpus_id = %s AND removed_at IS NULL",
                (corpus_id,),
            )
            doc_count = cur.fetchone()["count"]
        accumulated_result["step_1_members"] = {"active_docs": doc_count}
        update_task_state(task_id, state="running", step_no=1, result=accumulated_result)
        current_step = 1

    # Step 2: Policy & Gate evaluation
    if current_step < 2:
        if simulate_crash_at_step == 2:
            update_task_state(task_id, state="blocked", step_no=1, result=accumulated_result)
            raise RuntimeError("SIMULATED AGENT CRASH AT STEP 2 (POLICY GATE)")
        decision = gate.evaluate_build(corpus_id, attempted_by=f"agent-task:{task_id}")
        accumulated_result["step_2_gate"] = {
            "allowed": decision.allowed,
            "violations": len(decision.violations),
            "obligations": len(decision.obligations),
            "summary": decision.summary,
        }
        update_task_state(task_id, state="running", step_no=2, result=accumulated_result)
        current_step = 2

    # Step 3: Integrity verification
    if current_step < 3:
        if simulate_crash_at_step == 3:
            update_task_state(task_id, state="blocked", step_no=2, result=accumulated_result)
            raise RuntimeError("SIMULATED AGENT CRASH AT STEP 3 (INTEGRITY CHECK)")
        now = datetime.now(timezone.utc)
        integrity = corpus.verify_integrity(corpus_id, now)
        accumulated_result["step_3_integrity"] = {
            "consistent": integrity.consistent,
            "conclusive": integrity.conclusive,
            "source": "mvcc+bitemporal",
        }
        update_task_state(task_id, state="running", step_no=3, result=accumulated_result)
        current_step = 3

    # Step 4: Final synthesis
    accumulated_result["step_4_report"] = {
        "status": "COMPLETED",
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": "COMPLIANT" if accumulated_result["step_2_gate"]["allowed"] else "NON_COMPLIANT",
    }
    final_task = update_task_state(task_id, state="done", step_no=4, result=accumulated_result)
    return final_task

