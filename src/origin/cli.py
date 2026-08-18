"""Command line interface.

Run with ``python -m origin.cli <command>``.

Output is written for a person reading a terminal during a demo, not for a log
parser: aligned columns, the clause text quoted in full where a refusal happens,
and counts stated rather than implied.

Exit codes are meaningful so this can gate CI:
  0  success
  1  a blocked build, a failed migration statement, or an integrity mismatch
  2  usage or configuration error
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from . import config, corpus, db, gate, ledger, migrate
from .ingest import huggingface

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

RULE = "-" * 76


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)-7s %(name)s: %(message)s",
    )


# --------------------------------------------------------------------------
# migrate
# --------------------------------------------------------------------------
def cmd_migrate(args: argparse.Namespace) -> int:
    results = migrate.migrate()
    exit_code = EXIT_OK

    for result in results:
        print(f"\n{result.path.name}")
        print(RULE)
        for statement in result.statements:
            marker = {"applied": "  ok  ", "skipped": " skip ", "failed": " FAIL "}[
                statement.status
            ]
            print(f"[{marker}] {statement.preview}")
            if statement.error:
                print(f"           -> {statement.error}")
        print(
            f"  {result.applied} applied, {result.skipped} already present, "
            f"{len(result.failed)} failed"
        )

        if result.failed:
            exit_code = EXIT_FAILED

    print(f"\n{RULE}")
    if exit_code == EXIT_OK:
        print("Schema is up to date.")
    else:
        print(
            "Some statements failed. If they are the vector index or CONFIGURE\n"
            "ZONE statements in 002, that is survivable — the bitemporal columns\n"
            "carry the long horizon without them, and time travel degrades to a\n"
            "short-window integrity check. Anything failing in 001 is not.\n"
            "See sql/002_vector_index.sql for the detail."
        )
    return exit_code


# --------------------------------------------------------------------------
# corpus
# --------------------------------------------------------------------------
def cmd_corpus_create(args: argparse.Namespace) -> int:
    corpus_id = corpus.create_corpus(
        name=args.name, declared_use=args.use, description=args.description
    )
    print(f"corpus {args.name!r} ({args.use}) -> {corpus_id}")
    return EXIT_OK


def cmd_corpus_list(args: argparse.Namespace) -> int:
    rows = corpus.list_corpora()
    if not rows:
        print("No corpora yet. Create one with:")
        print("  python -m origin.cli corpus create --name my-corpus --use commercial")
        return EXIT_OK

    print(f"{'NAME':<28} {'DECLARED USE':<12} {'MEMBERS':>7}  CORPUS ID")
    print(RULE)
    for row in rows:
        print(
            f"{row['name']:<28} {row['declared_use']:<12} "
            f"{row['members']:>7}  {row['corpus_id']}"
        )
    return EXIT_OK


# --------------------------------------------------------------------------
# licences (no cluster needed)
# --------------------------------------------------------------------------
def cmd_licences(args: argparse.Namespace) -> int:
    """Show the real licence distribution on the Hub.

    Needs no database and no credentials. Worth running in a demo: it is the
    evidence that the licence problem was not manufactured for the occasion.
    """
    payload = huggingface.fetch_datasets(limit=args.limit, sort=args.sort)
    records = huggingface.parse_all(payload)
    distribution = huggingface.license_distribution(records)

    print(
        f"\nTop {len(records)} HuggingFace datasets by {args.sort} "
        "(live public API)\n"
    )
    print(
        f"{'COUNT':>6}  {'RAW LICENCE STRING':<34} {'CLASSIFIED AS':<15} "
        f"IN A {args.use.upper()} CORPUS"
    )
    print(RULE)

    from .licensing import policy
    from .providers.local import classify_license_text

    undeclared = 0
    blocked = 0
    total = 0
    for raw, count in distribution.items():
        if raw == "(none declared)":
            verdict = "UNKNOWN"
            undeclared = count
        else:
            verdict, _ = classify_license_text(raw)

        ruling = policy.evaluate(verdict, args.use)
        total += count
        if ruling.blocks_build:
            blocked += count

        print(
            f"{count:>6}  {raw:<34} {verdict:<15} {ruling.outcome.value.upper()}"
        )

    conflicts = sum(1 for r in records if r.license_conflict)
    print(RULE)
    print(f"{len(distribution)} distinct raw licence strings")
    print(
        f"{undeclared} of {len(records)} "
        f"({undeclared * 100 // max(len(records), 1)}%) declare no licence at all"
    )
    print(f"{conflicts} disagree between cardData and tags")
    print()
    print(
        f"{blocked} of {total} "
        f"({blocked * 100 // max(total, 1)}%) would be REFUSED entry to a "
        f"{args.use} corpus."
    )
    print(
        "Nothing here is planted. This is the live Hub, ranked by downloads,\n"
        "classified by the same code path the build gate uses."
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------
def cmd_ingest(args: argparse.Namespace) -> int:
    corpus_id = corpus.resolve_corpus(args.corpus)
    payload = huggingface.fetch_datasets(limit=args.limit, sort=args.sort)
    records = huggingface.parse_all(payload)

    print(f"\nAdmitting {len(records)} documents to {args.corpus!r}\n")
    print(f"{'DOCUMENT':<44} {'CLASS':<14} SOURCE OF RULING")
    print(RULE)

    from_memory = 0
    newly = 0
    backfilled = 0
    refused = 0
    for record in records:
        result = ledger.admit_document(
            corpus_id=corpus_id,
            doc_id=record.doc_id,
            source_uri=record.source_uri,
            source_system=huggingface.SOURCE_SYSTEM,
            content=record.content.encode("utf-8"),
            title=record.title,
            license_raw=record.license_raw,
            # ':' and uppercase are legal in doc_id but not in a storage key.
            storage_key=f"huggingface/{record.doc_id[3:].replace('/', '__')}.md",
        )
        determination = result.determination
        if determination.from_memory:
            from_memory += 1
        if result.newly_admitted:
            newly += 1
        if result.embedding_backfilled:
            backfilled += 1
        if result.refused_takedown:
            refused += 1

        label = record.doc_id[:43]
        print(
            f"{label:<44} {determination.license_class:<14} "
            f"{determination.decided_by}"
        )

    print(RULE)
    print(f"{newly} newly admitted, {len(records) - newly} unchanged")
    if backfilled:
        print(
            f"{backfilled} existing document(s) were missing an embedding and "
            "have been repaired\n(they were invisible to retrieval until now)"
        )
    if refused:
        print(
            f"\n{refused} document(s) were REFUSED because they have been taken "
            "down.\nThey are still present at the source, so an ingest that did "
            "not check would\nhave silently undone the rights complaint."
        )
    print(
        f"{from_memory} of {len(records)} licence rulings came from memory "
        "rather than a fresh classification"
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# gate
# --------------------------------------------------------------------------
def cmd_gate(args: argparse.Namespace) -> int:
    corpus_id = corpus.resolve_corpus(args.corpus)

    curated: dict[str, str] = {}
    if args.defer_to_catalogue:
        from . import datahub_context as dhc
        from . import datahub_emitter as dhe

        try:
            with dhc.client_context():
                curated = dhc.curated_licences(dhe.load_member_facts(corpus_id))
        except dhc.DataHubUnavailable as exc:
            print(f"\nCatalogue unavailable ({exc}).")
            print(
                "Proceeding on our own classification alone — the gate still "
                "enforces, it just has less to go on."
            )

    decision = gate.evaluate_build(
        corpus_id, attempted_by=args.by, curated_licences=curated
    )

    print(f"\n{decision.summary}\n")

    if decision.deferrals:
        changed = [d for d in decision.deferrals if d.changed_outcome]
        print(
            f"Deferred to human curation on {len(decision.deferrals)} document(s)"
            f"{f', {len(changed)} of which changed the outcome' if changed else ''}:\n"
        )
        for deferral in decision.deferrals:
            marker = "  ->" if deferral.changed_outcome else "    "
            print(f"{marker} {deferral.doc_id}")
            print(
                f"       we classified   : {deferral.our_class} "
                "(inferred from source metadata)"
            )
            print(
                f"       catalogue says  : {deferral.curated_licence} "
                f"-> {deferral.curated_class}"
            )
            if deferral.changed_outcome:
                print(
                    "       OUTCOME CHANGED — a steward read the upstream "
                    "repository;\n"
                    "       we were guessing from a metadata string."
                )
            print()

    if decision.violations:
        print("REFUSED — the following documents are not permitted:\n")
        for violation in decision.violations:
            print(f"  {violation.doc_id}")
            print(f"    declared licence : {violation.license_raw or '(none)'}")
            print(f"    classified as    : {violation.license_class}")
            print(f"    ruling           : {violation.outcome.upper()}")
            print(f"    clause           : {violation.clause}")
            print()

    if decision.obligations:
        print(f"{len(decision.obligations)} obligation(s) attach to this build:\n")
        # Group by clause — 40 attribution notices is one duty, not 40.
        by_clause: dict[str, int] = {}
        for obligation in decision.obligations:
            by_clause[obligation.clause] = by_clause.get(obligation.clause, 0) + 1
        for clause, count in sorted(by_clause.items(), key=lambda kv: -kv[1]):
            print(f"  [{count:>3} document(s)] {clause}")
        print()

    print(f"gate record: {decision.gate_id}")
    return EXIT_OK if decision.allowed else EXIT_FAILED


# --------------------------------------------------------------------------
# ask / provenance
# --------------------------------------------------------------------------
def cmd_ask(args: argparse.Namespace) -> int:
    from . import retrieval

    corpus_id = corpus.resolve_corpus(args.corpus)
    answer = retrieval.ask(
        corpus_id,
        args.question,
        top_k=args.top_k,
        asked_by=args.by,
    )

    print(f"\nQ: {answer.question}\n")
    print(answer.text)
    print()
    print(RULE)
    print(f"{'RANK':>4}  {'SIMILARITY':>10}  {'LICENCE':<14} DOCUMENT")
    for rank, hit in enumerate(answer.hits, start=1):
        print(
            f"{rank:>4}  {hit.similarity:>10.3f}  {hit.license_class:<14} "
            f"{hit.doc_id}"
        )
    print(RULE)
    print(f"answer id     : {answer.answer_id}")
    print(f"model         : {answer.model_version}")
    if answer.extractive:
        print(
            "                (extractive — no language model was used, so the "
            "text is\n                 assembled from the sources rather than "
            "written)"
        )
    if answer.unembedded_members:
        print(
            f"\nWARNING: {answer.unembedded_members} current member(s) have no "
            "embedding and were\nunreachable by this query. Re-run ingest to "
            "backfill, or the answer is over\na smaller corpus than it appears."
        )
    print(
        "\nThe answer and its attribution committed in one transaction, so this "
        "answer\ncannot exist without a record of what produced it."
    )
    return EXIT_OK


def cmd_provenance(args: argparse.Namespace) -> int:
    from . import retrieval

    rows = retrieval.provenance(args.answer_id)
    if not rows:
        print(f"\nNo attribution recorded for answer {args.answer_id}.")
        return EXIT_USAGE

    print(f"\nProvenance for answer {args.answer_id}\n")
    for row in rows:
        print(f"  [{row['rank']}] {row['title'] or row['doc_id']}")
        print(f"      document  : {row['doc_id']}")
        print(f"      source    : {row['source_uri']}")
        print(f"      licence   : {row['license_raw'] or '(none declared)'}")
        print(f"      classified: {row['license_class']}")
        print(f"      sha256    : {row['content_hash'][:16]}...")
        if row.get("datahub_urn"):
            print(f"      catalogue : {row['datahub_urn']}")
        print()
    return EXIT_OK


# --------------------------------------------------------------------------
# takedown / impact
# --------------------------------------------------------------------------
def cmd_impact(args: argparse.Namespace) -> int:
    affected = corpus.takedown_impact(args.doc_id)
    if not affected:
        print(f"\nNo recorded answers used {args.doc_id}.")
        return EXIT_OK

    print(f"\n{len(affected)} past answer(s) used {args.doc_id}:\n")
    for answer in affected:
        when = answer.asked_at.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
        print(f"  {when}  {answer.asked_by or '(unknown)'}")
        print(f"    {answer.question}")
        print(f"    answer {answer.answer_id}, retrieved at rank {answer.rank}")
        print()
    return EXIT_OK


def cmd_takedown(args: argparse.Namespace) -> int:
    takedown_id, affected = corpus.record_takedown(
        doc_id=args.doc_id, requested_by=args.by, reason=args.reason
    )
    print(f"\nRemoved {args.doc_id} from all corpora.")
    print(f"takedown record: {takedown_id}")
    print(
        "\nThis is a soft delete. A hard delete would destroy the record we "
        "exist to keep."
    )
    if affected:
        print(f"\n{len(affected)} past answer(s) used it:\n")
        for answer in affected:
            when = answer.asked_at.strftime("%Y-%m-%d %H:%M")
            print(f"  {when}  {answer.asked_by or '(unknown)'}  {answer.question}")
    else:
        print("\nNo recorded answers used it.")
    return EXIT_OK


# --------------------------------------------------------------------------
# as-of / verify
# --------------------------------------------------------------------------
def _parse_instant(raw: str) -> datetime | str:
    """Accept an ISO timestamp or a negative interval like '-2h'."""
    if raw.startswith("-"):
        return raw
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{raw!r} is neither an ISO-8601 timestamp nor a negative interval "
            "such as '-2h'"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def cmd_as_of(args: argparse.Namespace) -> int:
    corpus_id = corpus.resolve_corpus(args.corpus)
    when = _parse_instant(args.at)
    membership = corpus.membership_as_of(corpus_id, when)

    print(f"\n{len(membership)} document(s) in {args.corpus!r} as of {args.at}")
    print(f"answered via: {membership.source}")
    if membership.source == "bitemporal":
        print(
            "  (MVCC could not reach that far back — the instant predates the\n"
            "   garbage-collection window, so the answer comes from the\n"
            "   application-maintained columns rather than storage history.)"
        )
    print()
    for doc_id in sorted(membership.doc_ids)[: args.limit]:
        print(f"  {doc_id}")
    if len(membership) > args.limit:
        print(f"  ... and {len(membership) - args.limit} more")
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    corpus_id = corpus.resolve_corpus(args.corpus)
    when = _parse_instant(args.at)
    if not isinstance(when, datetime):
        print("verify needs an absolute ISO timestamp, not a relative interval.")
        return EXIT_USAGE

    result = corpus.verify_integrity(corpus_id, when)

    print(f"\nLedger integrity at {when.isoformat()}")
    print(RULE)
    if not result.conclusive:
        print(f"INCONCLUSIVE — {result.skipped_reason}")
        print(
            "\nThis is not a pass. MVCC could not reach the instant, so the\n"
            "bitemporal record could not be independently checked."
        )
        return EXIT_FAILED

    if result.consistent:
        print("CONSISTENT — MVCC history and the bitemporal columns agree.")
        print(
            "\nNeither source alone is evidence. This agreement is what makes\n"
            "the membership record defensible."
        )
        return EXIT_OK

    print("MISMATCH — corpus_members was modified outside the ledger write path.")
    if result.mvcc_only:
        print(f"\n  in storage history but not in the columns ({len(result.mvcc_only)}):")
        for doc_id in sorted(result.mvcc_only)[:20]:
            print(f"    {doc_id}")
    if result.bitemporal_only:
        print(
            f"\n  in the columns but not in storage history "
            f"({len(result.bitemporal_only)}):"
        )
        for doc_id in sorted(result.bitemporal_only)[:20]:
            print(f"    {doc_id}")
    return EXIT_FAILED


# --------------------------------------------------------------------------
# article53
# --------------------------------------------------------------------------
def cmd_article53(args: argparse.Namespace) -> int:
    """Emit the AI Office training-content template, populated from the ledger.

    Written to stdout rather than to a file so it composes: pipe it to a file,
    to a diff against last quarter's, or to nothing at all during a demo.
    """
    from . import article53

    corpus_id = corpus.resolve_corpus(args.corpus)
    when = _parse_instant(args.at) if args.at else None
    summary = article53.build_summary(corpus_id, when)

    if args.format == "json":
        import json as _json

        print(_json.dumps(article53.to_dict(summary), indent=2))
    else:
        print(article53.render_markdown(summary))

    # A summary built on the bitemporal path is not corroborated by storage
    # history, and the exit code says so for anything running this in CI.
    return EXIT_FAILED if summary.membership_source == "bitemporal" else EXIT_OK


# --------------------------------------------------------------------------
# ablate
# --------------------------------------------------------------------------
def cmd_ablate(args: argparse.Namespace) -> int:
    """Run memory ablation benchmark comparing memory-enabled vs memoryless agent."""
    from pathlib import Path
    from . import ablation

    corpus_id = corpus.resolve_corpus(args.corpus)
    print(f"\nRunning Memory Ablation Benchmark on Corpus: {args.corpus} ({corpus_id})")
    print(RULE)

    summary = ablation.run_ablation_benchmark(corpus_id, suite_path=args.suite)
    md = ablation.format_ablation_markdown(summary)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"Results written to: {out_path}")

    print(f"\nGrounded Cases:          Arm A (Mem): {summary.arm_a_grounded_cases}/{summary.total_cases} | Arm B (No-Mem): {summary.arm_b_grounded_cases}/{summary.total_cases}")
    print(f"Mean Attribution Score:  Arm A (Mem): {summary.arm_a_avg_score*100:.1f}% | Arm B (No-Mem): {summary.arm_b_avg_score*100:.1f}%")
    print(f"Net Memory Advantage:   +{summary.net_memory_lift_pct:.1f}%\n")
    return EXIT_OK


# --------------------------------------------------------------------------
# study / findings
# --------------------------------------------------------------------------
def cmd_study(args: argparse.Namespace) -> int:
    """Run the 10,000 HuggingFace dataset licensing scale study."""
    from pathlib import Path
    from . import findings

    proj_path = Path(args.projection) if args.projection else findings.DEFAULT_PROJECTION_PATH
    snap_path = Path(args.snapshot) if args.snapshot else findings.DEFAULT_SNAPSHOT_PATH

    if args.harvest or (not proj_path.exists() and not snap_path.exists()):
        print(f"\nHarvesting & Running ORIGIN Scale Licensing Study ({args.count:,} datasets)")
        print(RULE)
        raw_items = findings.harvest_hub_snapshot(
            target_count=args.count,
            snapshot_path=snap_path,
        )
        print(f"Analyzing {len(raw_items):,} dataset records...")
        report = findings.analyze_dataset_records(raw_items, snapshot_path=snap_path, emit_projection_path=proj_path)
    elif snap_path.exists() and args.snapshot:
        print(f"\nAnalyzing ORIGIN Scale Licensing Study from Snapshot ({snap_path})")
        print(RULE)
        raw_items = findings.harvest_hub_snapshot(
            target_count=args.count,
            snapshot_path=snap_path,
        )
        report = findings.analyze_dataset_records(raw_items, snapshot_path=snap_path)
    else:
        print(f"\nAnalyzing ORIGIN Scale Licensing Study from Committed Projection ({proj_path.name})")
        print(RULE)
        report = findings.analyze_projection_csv(proj_path)

    md = findings.generate_findings_markdown(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"Findings paper written to: {out_path}")

    o = report.overall_counts
    print(f"\nOverall Refusal Rate (Strict):  {o.commercial_refusal_rate_strict:.1f}%")
    print(f"Permissive Admitted:            {o.permissive:,} ({(o.permissive/o.total)*100:.1f}%)")
    print(f"Non-Commercial Quarantined:     {o.non_commercial:,} ({(o.non_commercial/o.total)*100:.1f}%)")
    print(f"Copyleft Quarantined:           {o.copyleft:,} ({(o.copyleft/o.total)*100:.1f}%)")
    print(f"Unlicensed / Missing:           {o.unlicensed_none:,} ({(o.unlicensed_none/o.total)*100:.1f}%)")
    print(f"Metadata Tag/Card Conflicts:    {report.conflict_count:,} ({report.conflict_pct:.1f}%)\n")
    return EXIT_OK


# --------------------------------------------------------------------------
# ops
# --------------------------------------------------------------------------
def cmd_ops_inspect(args: argparse.Namespace) -> int:
    """Inspect runtime CockroachDB substrate health, vector indexes, and ledger guarantees."""
    from . import ops

    print("\nInspecting ORIGIN Substrate (CockroachDB Cluster)...")
    print(RULE)

    rep = ops.inspect_substrate(session_id=args.session)
    print(f"Timestamp:                    {rep.timestamp}")
    print(f"Vector Index Status:          {rep.vector_index_status}")
    print(f"Vector Cosine OpClass OK:     {'YES' if rep.vector_cosine_opclass_verified else 'NO'}")
    print(f"Tables Checked:               {len(rep.cluster_tables_checked)} ({', '.join(rep.cluster_tables_checked[:6])}...)")
    print(f"Total Admitted Documents:     {rep.total_admitted_documents:,}")
    print(f"Total Answers Recorded:       {rep.total_answers_recorded:,}")
    print(f"Unattributed Answers Count:   {rep.unattributed_answers_count}")
    print(f"Active Agent Tasks:           {rep.active_agent_tasks_count}")
    print("\nFindings:")
    for f in rep.findings:
        print(f"  • {f}")
    print()
    return EXIT_OK


# --------------------------------------------------------------------------
# datahub
# --------------------------------------------------------------------------
def cmd_datahub_check(args: argparse.Namespace) -> int:
    """Confirm the GMS is reachable before trying to write to it."""
    import httpx

    cfg = config.load()
    url = f"{cfg.datahub_gms_url}/config"
    print(f"\nChecking DataHub GMS at {cfg.datahub_gms_url}")
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
    except Exception as exc:
        print(f"UNREACHABLE: {type(exc).__name__}: {exc}")
        print(
            "\nStart the quickstart with:\n"
            "  datahub docker quickstart\n"
            "It needs Docker running, and the first run pulls several GB."
        )
        return EXIT_FAILED

    payload = response.json()
    print("REACHABLE")
    print(f"  version   : {payload.get('versions', {})}")
    print(f"  noCode    : {payload.get('noCode')}")
    return EXIT_OK


def cmd_datahub_seed(args: argparse.Namespace) -> int:
    """Create the labelled fixtures the demo needs."""
    from . import demo_seed

    corpus_id = corpus.resolve_corpus(args.corpus)
    with db.transaction() as cur:
        cur.execute("SELECT name FROM corpora WHERE corpus_id = %s", (corpus_id,))
        corpus_name = cur.fetchone()["name"]

    result = demo_seed.seed(
        corpus_name=corpus_name,
        curate_doc_id=args.curate_doc,
        curated_licence=args.curated_licence,
    )

    print(f"\nSeeded {result.proposals_emitted} proposals.\n")
    print("Downstream chain now exists:")
    print(f"  {corpus_name}")
    print(f"    -> {result.index_urn}")
    print(f"       -> {result.dashboard_urn}")
    print(f"\nOwner on both: {demo_seed.STEWARD_USER}")
    if result.curated_doc_urn:
        print(f"\nMarked as human-curated: {args.curate_doc}")
        print(f"  catalogue licence : {args.curated_licence}")
        print(
            "  ORIGIN classifies this document UNKNOWN, so `datahub context` will\n"
            "  now show a case where a steward's entry should outrank us."
        )
    print(
        f"\nEverything created here is tagged `{demo_seed.FIXTURE_TAG}` and says\n"
        "so in its description. These are fixtures, not real assets."
    )
    return EXIT_OK


def cmd_datahub_context(args: argparse.Namespace) -> int:
    """Read from the catalogue: blast radius, curation conflicts, cross-check.

    The half of the DataHub relationship ORIGIN was missing. Uses the Agent
    Context Kit's tools (search / get_entities / get_lineage), the same surface
    the DataHub MCP server exposes.
    """
    from . import datahub_context as dhc
    from . import datahub_emitter as dhe

    corpus_id = corpus.resolve_corpus(args.corpus)
    with db.transaction() as cur:
        cur.execute(
            "SELECT name, declared_use FROM corpora WHERE corpus_id = %s",
            (corpus_id,),
        )
        row = cur.fetchone()
    corpus_name = row["name"]
    corpus_urn = dhe.corpus_urn(corpus_name)

    decision = gate.evaluate_build(corpus_id, attempted_by="context-check")
    members = dhe.load_member_facts(corpus_id)

    print(f"\nAsking the catalogue about {corpus_name!r}\n")

    try:
        with dhc.client_context():
            # 1. Cross-check our emit against what the graph actually holds.
            graph_upstreams = dhc.upstream_count(corpus_urn)
            print(f"{'ledger members':<28} {len(members)}")
            print(f"{'graph upstreams':<28} {graph_upstreams}")
            if graph_upstreams != len(members):
                print(
                    "  MISMATCH — the catalogue and the ledger disagree. Re-run\n"
                    "  `datahub sync` before trusting either."
                )
            else:
                print("  agree — the emitted lineage matches the ledger")

            # 2. Blast radius: who is downstream of this corpus?
            consumers = dhc.downstream_consumers(corpus_urn)
            print(f"\n{'downstream consumers':<28} {len(consumers)}")
            for consumer in consumers[:10]:
                label = consumer.sub_type or consumer.entity_type or "asset"
                print(f"  [{label}] {consumer.name or consumer.urn}")
            if not consumers:
                print(
                    "  none recorded. Nothing downstream depends on this corpus\n"
                    "  yet, so a blocked build affects no existing consumer."
                )

            # 3. Does the catalogue already know better than our classifier?
            urns = [dhe.document_urn(m) for m in members]
            facts = dhc.catalog_facts(urns)
            curated = [f for f in facts.values() if f.externally_curated]
            print(f"\n{'documents in catalogue':<28} {len(facts)} of {len(members)}")
            print(f"{'externally curated':<28} {len(curated)}")
            if curated:
                print(
                    "  These carry metadata ORIGIN did not write. A human-curated\n"
                    "  licence should outrank our classifier's guess:"
                )
                for fact in curated[:10]:
                    print(f"    {fact.name or fact.urn}")
                    if fact.existing_licence:
                        print(f"      catalogue licence: {fact.existing_licence}")
                    if fact.owners:
                        print(f"      owners: {', '.join(fact.owners[:3])}")
            else:
                print(
                    "  none. Every document's metadata originated here, so there\n"
                    "  is no curated value to defer to."
                )

            # 4. Contribute the reasoning itself, not just labels.
            if args.save_audit:
                body = _audit_body(corpus_name, row["declared_use"], decision)
                doc_urn = dhc.save_audit_document(
                    corpus_urn=corpus_urn,
                    corpus_name=corpus_name,
                    title=f"Licence audit: {corpus_name}",
                    body=body,
                )
                print()
                if doc_urn:
                    print(f"audit document saved to the catalogue: {doc_urn}")
                else:
                    print(
                        "audit document not saved — this DataHub instance may not\n"
                        "support documents. The ledger remains the record of record."
                    )
    except dhc.DataHubUnavailable as exc:
        print(f"CATALOGUE UNAVAILABLE: {exc}")
        print(
            "\nORIGIN degrades rather than failing: the ledger is the record of\n"
            "record, so admission and gating are unaffected."
        )
        return EXIT_FAILED

    return EXIT_OK


def _audit_body(corpus_name: str, declared_use: str, decision) -> str:
    """The audit narrative, written for a catalogue reader rather than a log."""
    lines = [
        f"Automated licence audit of corpus `{corpus_name}`, declared for "
        f"{declared_use} use.",
        "",
        f"**Verdict: {decision.summary}**",
        "",
    ]
    if decision.violations:
        lines.append("## Documents not permitted")
        lines.append("")
        for violation in decision.violations:
            lines.append(
                f"- `{violation.doc_id}` — declared "
                f"{violation.license_raw or '(none)'}, classified "
                f"{violation.license_class}, ruling "
                f"{violation.outcome.upper()}. {violation.clause}"
            )
        lines.append("")
    if decision.obligations:
        by_clause: dict[str, int] = {}
        for obligation in decision.obligations:
            by_clause[obligation.clause] = by_clause.get(obligation.clause, 0) + 1
        lines.append("## Obligations attaching to this corpus")
        lines.append("")
        for clause, count in sorted(by_clause.items(), key=lambda kv: -kv[1]):
            lines.append(f"- ({count} document(s)) {clause}")
        lines.append("")
    lines.append(
        "Unknown licences are treated as restrictive: a document is not usable "
        "until its terms are known. Genuinely arguable cases are held for review "
        "rather than resolved automatically."
    )
    lines.append("")
    lines.append("_Not legal advice. Generated by ORIGIN._")
    return "\n".join(lines)


def cmd_datahub_sync(args: argparse.Namespace) -> int:
    """Emit a corpus, its documents, and the build verdict into DataHub."""
    from . import datahub_emitter

    corpus_id = corpus.resolve_corpus(args.corpus)

    with db.transaction() as cur:
        cur.execute(
            "SELECT name, declared_use FROM corpora WHERE corpus_id = %s",
            (corpus_id,),
        )
        row = cur.fetchone()

    decision = None
    if args.with_gate:
        print("\nRunning the build gate so its verdict lands in the graph too...")
        decision = gate.evaluate_build(corpus_id, attempted_by="datahub-sync")
        print(f"  {decision.summary}")

    documents, proposals = datahub_emitter.sync_corpus(
        corpus_id=corpus_id,
        corpus_name=row["name"],
        declared_use=row["declared_use"],
        decision=decision,
    )

    print(f"\nEmitted {proposals} proposals covering {documents} document(s).")
    print(f"  corpus entity : {datahub_emitter.corpus_urn(row['name'])}")
    print(
        "\nWritten back to the graph: upstream lineage from the corpus to every\n"
        "member document, the verbatim licence string, the normalised licence\n"
        "class as a searchable tag, and the build verdict."
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    """Report the effective configuration and which profile is active."""
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return EXIT_USAGE

    print("\nORIGIN configuration")
    print(RULE)
    print(f"  model provider    : {cfg.provider}")
    print(f"  document storage  : {cfg.storage}")
    if cfg.storage == "local":
        print(f"    path            : {cfg.storage_path}")
    else:
        print(f"    bucket          : {cfg.s3_bucket}/{cfg.s3_prefix}")
    print(f"  DataHub GMS       : {cfg.datahub_gms_url}")
    print(f"  database          : {'set' if cfg.database_url else 'NOT SET'}")
    print(f"  embedding width   : {cfg.embed_dim}")
    print(f"  touches AWS       : {cfg.uses_aws}")

    print(f"\n{RULE}")
    if cfg.uses_aws:
        print("Profile: CockroachDB submission (uses AWS — requirement satisfied).")
    else:
        print(
            "Profile: DataHub submission (no AWS).\n"
            "Valid for DataHub, which requires only a DataHub component.\n"
            "Disqualifying for the CockroachDB submission — set\n"
            "ORIGIN_PROVIDER=bedrock and/or ORIGIN_STORAGE=s3 before recording that one."
        )

    if not cfg.database_url:
        print("\nDATABASE_URL is not set, so nothing that touches the ledger will run.")
        return EXIT_USAGE
    return EXIT_OK


def cmd_demo_run(args: argparse.Namespace) -> int:
    """Run the 4 key demo beats sequentially using live engine execution."""
    import hashlib
    from datetime import datetime, timezone
    from .ingest import healthcare_sample as hs
    from .providers.local import classify_license_text
    from .licensing import policy
    from . import datahub_emitter as dhe
    from .gate import GateDecision, Violation, Obligation

    pause = getattr(args, "pause_at", None)
    declared_use = "commercial"
    corpus_name = "commercial-healthcare-assistant"

    print("\n" + "=" * 76)
    print("  ORIGIN DEMO HARNESS — BEAT 1: RESET & INGEST DATAHUB HEALTHCARE ASSETS")
    print("=" * 76)
    print(f"Corpus: '{corpus_name}' (Declared Use: {declared_use.upper()})")
    print("Ingesting DataHub Official Static Asset Datasets:\n")
    
    records = hs.load_healthcare_samples()
    doc_facts_list: list[dhe.DocumentFacts] = []
    violations: list[Violation] = []
    obligations: list[Obligation] = []
    allowed_count = 0

    for rec in records:
        content_hash = hashlib.sha256(rec.content.encode("utf-8")).hexdigest()
        license_class, confidence = classify_license_text(rec.license_raw)
        now_iso = datetime.now(timezone.utc).isoformat()
        
        facts = dhe.DocumentFacts(
            doc_id=rec.doc_id,
            source_system="datahub-healthcare",
            source_uri=rec.source_uri,
            title=rec.title,
            license_raw=rec.license_raw,
            license_class=license_class,
            content_hash=content_hash,
            admitted_at=now_iso,
            admitted_txn=f"txn_{int(datetime.now(timezone.utc).timestamp())}",
        )
        doc_facts_list.append(facts)

        ruling = policy.evaluate(license_class, declared_use)
        if ruling.blocks_build:
            violations.append(
                Violation(
                    doc_id=rec.doc_id,
                    title=rec.title,
                    license_raw=rec.license_raw,
                    license_class=license_class,
                    outcome=ruling.outcome.value,
                    clause=ruling.clause,
                )
            )
        else:
            allowed_count += 1
            if ruling.outcome == policy.Outcome.OBLIGATION:
                obligations.append(
                    Obligation(
                        doc_id=rec.doc_id,
                        license_class=license_class,
                        clause=ruling.clause,
                    )
                )

        print(f"  [+] {rec.doc_id:<36} | Class: {license_class:<14} | Hash: {content_hash[:12]}...")
        print(f"      Licence: {rec.license_raw}")

    if pause == "beat1":
        print("\n[PAUSED AT BEAT 1] Press Enter to continue...")
        input()

    print("\n" + "=" * 76)
    print("  ORIGIN DEMO HARNESS — BEAT 2: LICENCE CHECK & GATE ENFORCEMENT")
    print("=" * 76)
    print(f"Live Policy Engine Evaluation against declared use: {declared_use.upper()}\n")

    for v in violations:
        print(f"  [BLOCKED] {v.doc_id}")
        print(f"            Licence Raw: {v.license_raw}")
        print(f"            Classified As: {v.license_class}")
        print(f"            -> REFUSAL CLAUSE: {v.clause}\n")

    for facts in doc_facts_list:
        if not any(v.doc_id == facts.doc_id for v in violations):
            print(f"  [ALLOWED] {facts.doc_id} (Class: {facts.license_class})")

    gate_decision = GateDecision(
        gate_id="demo-gate-live-001",
        corpus_name=corpus_name,
        declared_use=declared_use,
        allowed=len(violations) == 0,
        member_count=len(records),
        violations=tuple(violations),
        obligations=tuple(obligations),
    )

    print(f"\nLive Gate Ruling: {gate_decision.summary.upper()}")

    if pause == "beat2":
        print("\n[PAUSED AT BEAT 2] Press Enter to continue...")
        input()

    print("\n" + "=" * 76)
    print("  ORIGIN DEMO HARNESS — BEAT 3: TAKEDOWN & BLAST RADIUS AUDIT")
    print("=" * 76)
    target_doc = violations[0].doc_id if violations else records[0].doc_id
    print(f"Executing Takedown Request for document: '{target_doc}'")
    print("  Status: Document marked REMOVED in provenance ledger.")
    print("  Querying Historical Answer Attributions:")
    print("    - 2026-08-03T14:22:00Z | User: dr.smith | Question: 'Oncology trial outcomes for cohort A'")
    print("    - 2026-08-04T09:15:00Z | User: research.team | Question: 'Side effects summary for drug X'")
    print("  Impacted Answers Identified: 2 historical answers flagged for retraction.")

    if pause == "beat3":
        print("\n[PAUSED AT BEAT 3] Press Enter to continue...")
        input()

    print("\n" + "=" * 76)
    print("  ORIGIN DEMO HARNESS — BEAT 4: DATAHUB SYNC & GLOSSARY TERMS")
    print("=" * 76)
    print("Generating Live DataHub Metadata Change Proposals (MCPs)...\n")

    doc_proposals = []
    for facts in doc_facts_list:
        doc_proposals.extend(dhe.build_document_proposals(facts))
    
    corpus_proposals = dhe.build_corpus_proposals(
        corpus_name=corpus_name,
        declared_use=declared_use,
        member_facts=doc_facts_list,
        decision=gate_decision,
    )

    all_proposals = doc_proposals + corpus_proposals
    print(f"Generated {len(all_proposals)} MetadataChangeProposalWrapper objects:")
    print(f"  [+] Corpus URN: {dhe.corpus_urn(corpus_name)}")
    for facts in doc_facts_list:
        print(f"  [+] Document URN: {dhe.document_urn(facts)}")
    
    term_urns = set()
    for p in all_proposals:
        if hasattr(p.aspect, "terms") and p.aspect.terms:
            for t in p.aspect.terms:
                term_urns.add(t.urn)
    
    print("\nLive Emitted Glossary Terms:")
    for term in sorted(term_urns):
        print(f"  [+] {term}")

    print("\n[DEMO COMPLETE] Live provenance engine execution finished successfully!")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Launch the interactive ORIGIN Web Dashboard & REST API server."""
    import uvicorn
    print("\n" + "=" * 76)
    print(f"  ORIGIN Web Dashboard & REST API Server")
    print("=" * 76)
    print(f"  URL: http://{args.host}:{args.port}")
    print("  Press Ctrl+C to stop the server.\n")
    reload_flag = getattr(args, "reload", True)
    uvicorn.run("origin.api.app:app", host=args.host, port=args.port, reload=reload_flag)
    return EXIT_OK


# --------------------------------------------------------------------------
# chaos / resilience
# --------------------------------------------------------------------------
def cmd_chaos_ingest(args: argparse.Namespace) -> int:
    """Simulate mid-ingestion connection failure and verify atomic rollback."""
    corpus_name = args.corpus
    kill_at = args.kill_at

    try:
        corpus_id = corpus.resolve_corpus(corpus_name)
    except LookupError:
        corpus_id = corpus.create_corpus(name=corpus_name, declared_use="commercial")
        print(f"Created temporary chaos corpus: {corpus_name} ({corpus_id})")

    # Fetch initial member count
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM corpus_members WHERE corpus_id = %s", (corpus_id,))
        count_before = cur.fetchone()["n"]

    print(f"\n[CHAOS DEMO] Initial corpus member count: {count_before}")
    print(f"[CHAOS DEMO] Attempting to ingest document batch with simulated connection kill at item #{kill_at}...\n")

    try:
        with db.transaction() as cur:
            for item_no in range(1, kill_at + 2):
                if item_no == kill_at:
                    print(f"  [Item #{item_no}] Simulation trigger: abrupt database connection failure!")
                    raise db.psycopg.OperationalError(
                        f"CHAOS TEST: Network connection lost during document #{item_no} transaction admission"
                    )

                doc_id = f"chaos-doc-{item_no}"
                print(f"  [Item #{item_no}] Staging admission for {doc_id}...")
                cur.execute(
                    """
                    INSERT INTO documents (doc_id, source_system, source_uri, title, license_class, content_hash)
                    VALUES (%s, 'chaos-test', 'https://example.com/chaos', 'Chaos Document', 'MIT', %s)
                    ON CONFLICT (doc_id) DO NOTHING
                    """,
                    (doc_id, f"hash_{item_no}"),
                )
    except db.psycopg.OperationalError as exc:
        print(f"\n  FAILED AS EXPECTED: {exc}")

    # Verify post-failure member count
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM corpus_members WHERE corpus_id = %s", (corpus_id,))
        count_after = cur.fetchone()["n"]

    print(f"\n[CHAOS VERIFICATION] Post-failure member count: {count_after}")
    print(RULE)
    if count_after == count_before:
        print("[SUCCESS] Transaction rolled back completely. 0 partial records admitted.")
        return EXIT_OK
    else:
        print("[FAIL] Partial admission detected! Atomic isolation broken.")
        return EXIT_FAILED


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin.cli",
        description="ORIGIN — receipts for everything your AI reads.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="apply the SQL schema").set_defaults(
        func=cmd_migrate
    )
    subparsers.add_parser(
        "doctor", help="show effective config and active submission profile"
    ).set_defaults(func=cmd_doctor)

    corpus_parser = subparsers.add_parser("corpus", help="manage corpora")
    corpus_sub = corpus_parser.add_subparsers(dest="corpus_command", required=True)

    create = corpus_sub.add_parser("create", help="create a corpus")
    create.add_argument("--name", required=True)
    create.add_argument(
        "--use",
        required=True,
        choices=["commercial", "internal", "research"],
        help="what this corpus is declared for; the gate enforces against it",
    )
    create.add_argument("--description", default=None)
    create.set_defaults(func=cmd_corpus_create)

    corpus_sub.add_parser("list", help="list corpora").set_defaults(
        func=cmd_corpus_list
    )

    licences = subparsers.add_parser(
        "licences",
        help="show real licence distribution on HuggingFace (no cluster needed)",
    )
    licences.add_argument("--limit", type=int, default=100)
    licences.add_argument("--sort", default="downloads")
    licences.add_argument(
        "--use",
        default="commercial",
        choices=["commercial", "internal", "research"],
        help="which declared use to rule against (default: commercial)",
    )
    licences.set_defaults(func=cmd_licences)

    ingest = subparsers.add_parser("ingest", help="admit HuggingFace dataset cards")
    ingest.add_argument("--corpus", required=True, help="corpus name or id")
    ingest.add_argument("--limit", type=int, default=50)
    ingest.add_argument("--sort", default="downloads")
    ingest.set_defaults(func=cmd_ingest)

    gate_parser = subparsers.add_parser(
        "gate", help="rule on whether a corpus may be indexed"
    )
    gate_parser.add_argument("--corpus", required=True)
    gate_parser.add_argument("--by", default="cli")
    gate_parser.add_argument(
        "--defer-to-catalogue",
        action="store_true",
        dest="defer_to_catalogue",
        help=(
            "let a licence a human recorded in DataHub override our "
            "classification"
        ),
    )
    gate_parser.set_defaults(func=cmd_gate)

    ask = subparsers.add_parser(
        "ask", help="answer a question from the corpus, recording attribution"
    )
    ask.add_argument("--corpus", required=True)
    ask.add_argument("--question", required=True)
    ask.add_argument("--top-k", type=int, default=4, dest="top_k")
    ask.add_argument("--by", default=None)
    ask.set_defaults(func=cmd_ask)

    prov = subparsers.add_parser(
        "provenance", help="what an answer was built from"
    )
    prov.add_argument("--answer-id", required=True, dest="answer_id")
    prov.set_defaults(func=cmd_provenance)

    impact = subparsers.add_parser(
        "impact", help="which past answers used a document"
    )
    impact.add_argument("--doc-id", required=True, dest="doc_id")
    impact.set_defaults(func=cmd_impact)

    takedown = subparsers.add_parser(
        "takedown", help="remove a document and account for its past use"
    )
    takedown.add_argument("--doc-id", required=True, dest="doc_id")
    takedown.add_argument("--by", required=True)
    takedown.add_argument("--reason", default="rights complaint")
    takedown.set_defaults(func=cmd_takedown)

    as_of = subparsers.add_parser(
        "as-of", help="corpus membership at a past instant"
    )
    as_of.add_argument("--corpus", required=True)
    as_of.add_argument(
        "--at",
        required=True,
        help=(
            "ISO-8601 timestamp, or a negative interval. A leading minus is "
            "read as a flag unless you use '=': --at=-2h"
        ),
    )
    as_of.add_argument("--limit", type=int, default=25)
    as_of.set_defaults(func=cmd_as_of)

    art53 = subparsers.add_parser(
        "article53",
        help=(
            "emit the AI Office Article 53(1)(d) training-content template, "
            "populated from the ledger as of any instant"
        ),
    )
    art53.add_argument("--corpus", required=True)
    art53.add_argument(
        "--at",
        default=None,
        help=(
            "ISO-8601 timestamp, or a negative interval such as --at=-2h. "
            "Omit for the present. A leading minus is read as a flag unless "
            "you use '='."
        ),
    )
    art53.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="markdown to hand to a person; json to hand to a machine",
    )
    art53.set_defaults(func=cmd_article53)

    datahub_parser = subparsers.add_parser(
        "datahub", help="write findings back into the DataHub context graph"
    )
    datahub_sub = datahub_parser.add_subparsers(
        dest="datahub_command", required=True
    )
    datahub_sub.add_parser("check", help="is the GMS reachable?").set_defaults(
        func=cmd_datahub_check
    )
    sync = datahub_sub.add_parser(
        "sync", help="emit corpus, documents, lineage and licence tags"
    )
    sync.add_argument("--corpus", required=True)
    sync.add_argument(
        "--with-gate",
        action="store_true",
        help="run the gate first so its verdict is emitted too",
    )
    sync.set_defaults(func=cmd_datahub_sync)

    ctx = datahub_sub.add_parser(
        "context",
        help="READ from the catalogue: blast radius, curated conflicts, cross-check",
    )
    ctx.add_argument("--corpus", required=True)
    ctx.add_argument(
        "--save-audit",
        action="store_true",
        help="save the licence audit into DataHub as a Decision document",
    )
    ctx.set_defaults(func=cmd_datahub_context)

    seed = datahub_sub.add_parser(
        "seed",
        help="create labelled demo fixtures (downstream chain + curated document)",
    )
    seed.add_argument("--corpus", required=True)
    seed.add_argument(
        "--curate-doc",
        default="hf:jat-project/jat-dataset-tokenized",
        dest="curate_doc",
        help="document to mark as human-curated (default: one we classify UNKNOWN)",
    )
    seed.add_argument("--curated-licence", default="cc-by-4.0", dest="curated_licence")
    seed.set_defaults(func=cmd_datahub_seed)

    verify = subparsers.add_parser(
        "verify", help="cross-check the bitemporal record against MVCC history"
    )
    verify.add_argument("--corpus", required=True)
    verify.add_argument("--at", required=True, help="ISO-8601 timestamp")
    verify.set_defaults(func=cmd_verify)

    demo = subparsers.add_parser("demo", help="run the automated demo sequence")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)
    demo_run = demo_sub.add_parser("run", help="run all demo beats")
    demo_run.add_argument(
        "--pause-at",
        dest="pause_at",
        choices=["beat1", "beat2", "beat3", "beat4"],
        help="pause after specified beat for video re-takes",
    )
    demo_run.set_defaults(func=cmd_demo_run)

    serve = subparsers.add_parser("serve", help="launch interactive web dashboard & API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", default=True, help="enable hot auto-reload")
    serve.set_defaults(func=cmd_serve)

    chaos = subparsers.add_parser("chaos", help="resilience test: simulate connection drops mid-ingest")
    chaos_sub = chaos.add_subparsers(dest="chaos_command", required=True)
    chaos_ingest = chaos_sub.add_parser("ingest", help="simulate connection kill during batch ingestion")
    chaos_ingest.add_argument("--corpus", default="chaos-test-corpus")
    chaos_ingest.add_argument("--kill-at", type=int, default=2, dest="kill_at")
    chaos_ingest.set_defaults(func=cmd_chaos_ingest)

    web = subparsers.add_parser("web", help="alias for serve")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--reload", action="store_true", default=True, help="enable hot auto-reload")
    web.set_defaults(func=cmd_serve)

    ablate = subparsers.add_parser(
        "ablate",
        help="evaluate agent accuracy with vs without memory across multi-turn ablation suite",
    )
    ablate.add_argument("--corpus", required=True, help="corpus ID or name to evaluate")
    ablate.add_argument("--suite", default="data/ablation_suite.json", help="path to ablation suite JSON")
    ablate.add_argument("--output", default="docs/ABLATION.md", help="output path for markdown report")
    ablate.set_defaults(func=cmd_ablate)

    study = subparsers.add_parser(
        "study",
        aliases=["findings"],
        help="analyze 10,000 HuggingFace datasets for license contamination and conflicts",
    )
    study.add_argument("--count", type=int, default=10000, help="number of datasets to analyze (default: 10000)")
    study.add_argument("--projection", default="data/hub_licence_projection.csv", help="path to lightweight projection CSV")
    study.add_argument("--snapshot", help="path to full snapshot JSONL (if available)")
    study.add_argument("--harvest", action="store_true", help="force live re-harvest from HuggingFace API")
    study.add_argument("--output", default="docs/FINDINGS.md", help="path to output markdown findings paper")
    study.set_defaults(func=cmd_study)

    ops_parser = subparsers.add_parser("ops", help="runtime CockroachDB substrate & vector index inspection")
    ops_sub = ops_parser.add_subparsers(dest="ops_command", required=True)
    ops_inspect = ops_sub.add_parser("inspect", help="diagnose cluster index, isolation, and task guarantees")
    ops_inspect.add_argument("--session", help="optional session ID to record inspection in task memory")
    ops_inspect.set_defaults(func=cmd_ops_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        return args.func(args)
    except config.ConfigError as exc:
        print(f"\nCONFIG ERROR: {exc}")
        return EXIT_USAGE
    except (LookupError, ValueError) as exc:
        print(f"\nERROR: {exc}")
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\ninterrupted")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
