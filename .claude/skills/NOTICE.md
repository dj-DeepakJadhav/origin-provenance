# Third-party attribution — CockroachDB Agent Skills

The skill directories in this folder are **not original work of this project**.
They are vendored, unmodified, from:

| | |
|---|---|
| Project | CockroachDB Agent Skills |
| Source | https://github.com/cockroachlabs/cockroachdb-skills |
| Copyright | Copyright © Cockroach Labs, Inc. |
| Licence | Apache License 2.0 — full text in [`LICENSE`](LICENSE) |
| Vendored | 2026-08-17 |

## What is actually here

Vendored subset — **6 of the 10 published domains carry skill content**; the
remaining four directories exist in the upstream layout but are empty here.

| Domain | Skills |
|---|---|
| `cockroachdb-security-and-governance` | 12 |
| `cockroachdb-observability-and-diagnostics` | 7 |
| `cockroachdb-operations-and-lifecycle` | 7 |
| `cockroachdb-onboarding-and-migrations` | 4 |
| `cockroachdb-application-development` | 3 |
| `cockroachdb-query-and-schema-design` | 1 |
| `cockroachdb-cost-and-usage-management` | 0 (empty) |
| `cockroachdb-integrations-and-ecosystem` | 0 (empty) |
| `cockroachdb-performance-and-scaling` | 0 (empty) |
| `cockroachdb-resilience-and-disaster-recovery` | 0 (empty) |
| **Total** | **34 skills across 6 domains** |

Stated exactly rather than rounded up, because the count is checkable and a
reader who counts should find what this file says.

## Which skills this project actually consulted

- `cockroachdb-query-and-schema-design` — vector index opclass and schema
  conventions, while building `sql/002`–`sql/008`
- `cockroachdb-application-development` — transaction design, informing the
  single-transaction atomic turn write in `agent.py`
- `cockroachdb-observability-and-diagnostics` — informing `/api/v1/metrics`

## One finding worth recording

Grepping the vendored skills for `VECTOR INDEX`, `opclass`, and
`vector_cosine_ops` returns **no guidance on operator classes**. The defect this
project found — `CREATE VECTOR INDEX` silently defaulting to `vector_l2_ops`, so
cosine (`<=>`) queries bypass the index entirely — would therefore not have been
caught by following these skills. See `sql/005_vector_opclass.sql` for the
before/after `EXPLAIN` evidence.

Offered as a contribution back, not a criticism: the skills are well-organised and
genuinely useful, and this is a gap worth filling upstream.

## Modifications

None. Files are vendored as published. Any future edits must be noted here, per
Apache-2.0 §4(b).
