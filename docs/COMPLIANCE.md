# ORIGIN and the EU AI Act

**Regulation (EU) 2024/1689, as amended by the Digital Omnibus on AI,
Regulation (EU) 2026/1744.**

This document maps ORIGIN's mechanisms onto specific obligations. It is written
for a reader who knows the Act and wants to see whether the code does what the
README implies — so every claim points at a file and a line, and the section on
what ORIGIN *cannot* do is longer than most of the sections on what it can.

The demo narration deliberately avoids this vocabulary. That is an audience
choice, not an absence of one: "which answers used this document?" needs no
regulatory framing to land. This document is the same system described to the
other audience.

> **Not legal advice.** The permitted-use matrix encodes a conservative reading
> of common licence families so a machine can enforce *something* consistently
> and explainably. Real deployment requires counsel to own that matrix. See
> [Limits](#what-origin-does-not-do).

---

## Why Article 53 and not the rest of the Act

As of **August 2026**, the Act's obligations sit in three very different states,
and the difference is the whole reason ORIGIN targets what it targets.

| Obligation set | Applies from | State |
|---|---|---|
| Prohibited practices (Art 5), AI literacy (Art 4) | 2 Feb 2025 | In force |
| **GPAI provider obligations (Art 53)** | **2 Aug 2025** | **In force** |
| **AI Office enforcement powers over GPAI (Art 88–94, 101)** | **2 Aug 2026** | **In force — as of five days before this was written** |
| Transparency / marking of synthetic content (Art 50); new NCII and CSAM prohibition | 2 Dec 2026 | Deferred / added by the Omnibus |
| High-risk, standalone Annex III (Art 8–27) | Postponed to **2 Dec 2027** | Deferred 16 months |
| High-risk, embedded Annex I products | Postponed to **2 Aug 2028** | Deferred 12 months |

Penalties are tiered by what was breached:

| Breach | Maximum |
|---|---|
| Prohibited practices (Art 5) | **€35M or 7%** of worldwide annual turnover |
| **GPAI model obligations (Art 53, 55)** | **€15M or 3%** |
| Other AI system breaches | **€7.5M or 1%** |

The Digital Omnibus on AI was published in the Official Journal on 24 July 2026
and entered into force on 27 July 2026. It deferred the high-risk regime. **It
did not defer Article 53.**

So the position ORIGIN takes is narrow and deliberate:

> The training-data transparency and copyright obligations on GPAI providers are
> the part of the AI Act that is live, enforceable, and backed by penalties of up
> to **€15,000,000 or 3% of worldwide annual turnover**, whichever is higher
> (Art 101). Everything else is a 2027–2028 problem. ORIGIN is built for the part
> that is a 2026 problem.

GPAI models placed on the market **before** 2 Aug 2025 have until **2 Aug 2027**
to publish their training-content summary — which is the deadline most incumbent
providers are actually working to.

---

## The scope distinction that matters most

**A RAG retrieval corpus is not training data, and Article 53(1)(d) does not
apply to it.**

This has to be said before any mapping table, because getting it wrong is the
most common error in this space and it invalidates everything downstream.

- **Art 53** binds *providers of general-purpose AI models*. Its subject is the
  content a model was **trained** on.
- ORIGIN's demo operates on a **retrieval corpus** — documents a system reads at
  inference time. Different legal object, different obligations.

What actually attaches to a RAG corpus in 2026:

| Concern | Instrument |
|---|---|
| Reproducing or adapting licensed text | Copyright law generally; Directive (EU) 2019/790 (DSM) |
| Text-and-data-mining rights reservations | **DSM Art 4(3)** — opt-outs must be honoured |
| Personal data in the corpus | GDPR — lawful basis, minimisation, erasure |
| Corpus quality, if the surrounding system is high-risk | **AI Act Art 10** (from Dec 2027) |
| Contractual terms of the source | Not regulation, but the thing that actually gets litigated |

**So why claim Article 53 relevance at all?** Because the mechanism is
substrate-neutral. A provenance ledger that records source, verbatim licence,
normalised permitted-use class, content hash and admission timestamp for every
document in a *retrieval* corpus is the same ledger you need for a *training*
corpus. ORIGIN demonstrates the machinery against the data it could legally
obtain; the obligation it is shaped for is Art 53(1)(d).

Everything in the table below is marked accordingly:

- **Direct** — ORIGIN implements this as it stands.
- **By analogy** — the mechanism would satisfy this if pointed at training data.
- **Partial** — ORIGIN produces an input to the obligation, not the obligation.

---

## Article mapping

### Article 53(1)(c) — Copyright policy

> *Providers shall put in place a policy to comply with Union law on copyright
> and related rights, and in particular to identify and comply with a reservation
> of rights expressed pursuant to Article 4(3) of Directive (EU) 2019/790.*

**Direct.** This is the obligation ORIGIN implements most completely, because a
"policy" that cannot refuse anything is not a policy.

| Mechanism | Code |
|---|---|
| Verbatim licence text captured at admission and never normalised in place | [`ledger.admit_document`](src/origin/ledger.py:268) — `license_raw` stored alongside the derived `license_class` |
| Messy real-world strings normalised into permitted-use classes | [`ledger.classify_license`](src/origin/ledger.py:128) |
| Permitted-use matrix — the policy itself, as enforceable data | [`licensing/policy.py:75`](src/origin/licensing/policy.py:75) |
| A rights reservation *blocks*, and the clause is quoted | [`gate.evaluate_build`](src/origin/gate.py:94) |
| Every build attempt recorded, allowed or blocked | [`gate.py:161`](src/origin/gate.py:161) → `build_gates` |
| A takedown cannot be silently undone by the next scheduled ingest | [`ledger.py:303`](src/origin/ledger.py:303) |

Three properties worth naming, because they are what distinguishes a policy from
a disclaimer:

1. **Unknown fails closed.** An unrecognised licence blocks the build
   ([`policy.py:180`](src/origin/licensing/policy.py:180)). The tempting
   alternative — pass it and log a warning — is precisely how unlicensed material
   reaches a shipped product.
2. **Genuinely arguable cases return `REVIEW`, not a verdict.** Copyleft in a
   commercial corpus stops the build and names a human
   ([`policy.py:96`](src/origin/licensing/policy.py:96)). A system that resolves
   that automatically is lying in one direction or the other.
3. **The refusal is explainable without re-running anything.** The clause is
   persisted with the violation, phrased for a human reader.

**Gap:** ORIGIN reads rights reservations from *metadata* — licence fields on
HuggingFace dataset cards. A complete Art 4(3) implementation must also honour
machine-readable reservations expressed at the point of access: `robots.txt`,
TDM Reservation Protocol headers, `ai.txt`. Not implemented.

---

### Article 53(1)(d) — Public summary of training content

> *Providers shall draw up and make publicly available a sufficiently detailed
> summary about the content used for training of the general-purpose AI model,
> according to a template provided by the AI Office.*

**By analogy** — see the scope distinction above.

The Commission published the mandatory template in July 2025. It requires, among
other things, model identifiers, data sources broken down by type, the handling
of rights reservations, a contact point for rightsholders, and a version history
with a last-updated date.

What ORIGIN already holds against that template:

| Template expects | ORIGIN has | Where |
|---|---|---|
| Data sources by type and provenance | `source_system`, `source_uri` per document | `documents` table |
| Licensing status of the content | `license_raw` + `license_class` + rationale | [`ledger.py:128`](src/origin/ledger.py:128) |
| How rights reservations were handled | `build_gates` verdicts and `takedowns` | [`gate.py:161`](src/origin/gate.py:161) |
| Version history and date of last update | Every row is bitemporal; the whole corpus is addressable at any instant | [`corpus.membership_as_of`](src/origin/corpus.py:167) |
| A summary *as at a stated date* | `AS OF SYSTEM TIME`, one query | [`cli.cmd_as_of`](src/origin/cli.py:395) |

That last row is the interesting one and it is the reason the project uses
CockroachDB. The template asks providers to describe the corpus *as it stood* at
a point in time. On a conventional database that requires having snapshotted the
whole corpus, on a schedule, indefinitely, in anticipation of being asked. On
MVCC storage it is a `WHERE` clause with a timestamp.

**Built.** [`origin article53`](src/origin/article53.py) emits the template's
section structure populated from the ledger, at any instant the ledger can still
reach:

```bash
origin article53 --corpus hub-commercial                      # as it stands
origin article53 --corpus hub-commercial --at=-2h             # as it stood
origin article53 --corpus hub-commercial --at=2026-08-06T12:00:00+00:00
origin article53 --corpus hub-commercial --format json
```

Three things about that command are the reason it is worth more than the prose
above it.

**It reports its own evidentiary grade rather than a number.** Within the MVCC
horizon the report says membership was read from storage history and that the
figure *"does not depend on trusting ORIGIN"*. Outside it, the same command
reports the same corpus as **"Asserted, not verifiable"**, names the
garbage-collection horizon as the reason, and exits **1**. A generator that
returned the same confident document count either way would be the exact failure
this project exists to argue against.

**It renders the fields it cannot populate.** Nine of them, each attached to a
template section and each saying why — crawl-time rights reservations
(`robots.txt`, TDM Reservation Protocol, `ai.txt`), volume in the template's
units, illegal-content measures, lawfulness of access, the rightsholder contact
point. A report that emitted only its populated sections would read as complete
coverage of a template it covers roughly half of.

**It refuses to launder silence into a pass.** A corpus with no recorded gate
decisions gets an explicit paragraph saying that is not evidence of compliance,
because a corpus with no blocks either had no violations or was never gated.

The tests in [`tests/test_article53.py`](tests/test_article53.py) pin those
properties rather than the output format, on the theory that the realistic
failure mode is not a crash — it is someone later tidying the report into
something that reads like a clean bill of health.

---

### Article 53(1)(a) and Annex XI — Technical documentation

**Partial.** ORIGIN produces the data-provenance portion of Annex XI and nothing
else. Annex XI also requires model architecture, training compute, energy
consumption, design specifications and evaluation results. ORIGIN has no view of
any of those and does not pretend to.

Where its portion lands: [`cli.cmd_datahub_sync`](src/origin/cli.py:628) writes
corpus lineage, verbatim licence strings, normalised licence classes and the
build verdict into DataHub — so the documentation lives in the catalogue the
organisation already uses rather than in a PDF nobody can find.

---

### Article 12 and Article 19 — Record-keeping and automatically generated logs

*(High-risk regime. Applies from 2 Dec 2027.)*

**Direct**, in substance, though ORIGIN logs corpus and answer events rather than
system-level operation.

The evidentiary argument is the part worth reading:

| Property | Mechanism |
|---|---|
| Admission is atomic — bytes, hash, licence ruling, membership and timestamp commit together or not at all | [`ledger.admit_document`](src/origin/ledger.py:268) |
| An answer and its attributions commit in one transaction, so an answer with no recorded sources is impossible | [`corpus.record_answer`](src/origin/corpus.py:272) |
| The timestamp is the cluster's own logical clock, not an application value | `db.cluster_logical_timestamp` |
| Silent mutation of a source document is detectable after the fact | SHA-256 at [`ledger.content_hash`](src/origin/ledger.py:98) |
| Tampering with the record is *detected*, not merely discouraged | [`corpus.verify_integrity`](src/origin/corpus.py:231) |

`verify_integrity` deserves its own note, because it is the mechanism most
directly aimed at an auditor. Membership is derivable two independent ways —
storage history (`AS OF SYSTEM TIME`, unforgeable by application code, bounded by
garbage collection) and bitemporal columns (`admitted_at` / `removed_at`,
unbounded, but only as honest as this codebase). **Neither alone is evidence.
Agreement between them is.** A mismatch means `corpus_members` was written outside
the ledger's own path, and it is reported rather than reconciled.

---

### Article 14 — Human oversight

*(High-risk regime.)*

**Partial.** ORIGIN has no oversight of an AI *system's* operation. What it does
have is oversight of its own automated judgements, which is a narrower thing
honestly labelled:

- A human correction **supersedes rather than overwrites**, so "what did we
  think, and when did we stop thinking it?" stays answerable
  ([`ledger.confirm_determination`](src/origin/ledger.py:503)).
- Corrections are `human_confirmed` and carry higher strength, so they outrank
  model rulings in future near-match resolution
  ([`ledger.py:198`](src/origin/ledger.py:198)).
- Documents already admitted under a superseded ruling are re-stamped, so a
  correction is not cosmetic ([`ledger.py:554`](src/origin/ledger.py:554)).
- `REVIEW` outcomes route to a human by stopping the build rather than by filing
  a ticket someone may read.

---

### Article 10 — Data and data governance

*(High-risk regime. Applies from 2 Dec 2027.)*

**By analogy.** Art 10(2)(b) requires examination of "data collection processes
and the origin of the data". That is the ledger's entire purpose. But Art 10 also
requires examination for bias, representativeness, and statistical suitability for
the intended purpose — and ORIGIN assesses **rights, not quality**. A corpus can
pass every ORIGIN gate and be badly biased. Nothing here detects that.

---

### GPAI Code of Practice — Copyright chapter

The Code of Practice for general-purpose AI, published July 2025, is voluntary,
but adherence carries a presumption of conformity with the corresponding Art 53
obligations. Its Copyright chapter is where ORIGIN's mechanisms land most
squarely, so it is worth mapping separately from the Regulation itself.

| Commitment, in substance | ORIGIN | Notes |
|---|---|---|
| Draw up, keep current, and **implement** a copyright policy | [`policy.py`](src/origin/licensing/policy.py) + [`gate.py`](src/origin/gate.py) | The word carrying the weight is *implement* — a policy with no enforcement point leaves no trace distinguishable from no policy |
| Identify and comply with rights reservations expressed by machine-readable means | Partial | Metadata licence fields only. No `robots.txt`, TDM Reservation Protocol, or `ai.txt` handling |
| Reproduce and extract only lawfully accessible content | Not implemented | ORIGIN rules on what a source *declares*; it does not assess whether access was lawful |
| Mitigate the risk of infringing outputs | Not implemented | Output-side control. ORIGIN is entirely input-side |
| Designate a contact point and enable rightsholder complaints | Partial | [`corpus.record_takedown`](src/origin/corpus.py:344) handles the complaint *once received*, and answers the question a complaint actually raises — what did this document already affect. There is no intake channel |

The pattern across that table is worth stating plainly: **ORIGIN covers the
admission boundary thoroughly and the crawl and output boundaries not at all.**
That is a scope choice, not an oversight, but a reader assessing coverage should
see the shape of it.

---

## Reading this from the supervisor's side

Everything above is written from the position of a party trying to comply. A
supervisor reads the same system with a different question: *not "does this help
us comply?" but "can any of this be relied upon?"*

Who that supervisor is depends on the system. Enforcement is split three ways:

| Body | Scope |
|---|---|
| **AI Office** (Commission) | Providers of GPAI models; AI systems from the same provider or business group; systems integrated into VLOPs designated under the DSA |
| **National competent authorities** | All other AI systems |
| **European Data Protection Supervisor** | AI systems used by EU institutions themselves |

For a GPAI provider — the party ORIGIN is shaped for — the supervisor is the AI
Office, and it has four powers worth designing against:

1. **Model evaluations**, conducted itself or through appointed independent experts
2. **Access requests** — requiring a provider to grant access for evaluation
3. **Corrective measures** — up to restricting a model's availability
4. **Requests for information**, simple or formal, to verify compliance

The fourth is the one that touches ORIGIN directly, and it is the realistic
interface: **most supervision begins as an RFI, not a raid.** A provenance ledger
is worth exactly what it can produce when a formal request arrives, within the
time the request allows. So the useful design question is not "is our record
good?" but "what can we hand over, how fast, and which parts of it would survive
being challenged?"

That reframing is why the table below is split the way it is.

Four observations for that reader, offered because they are the parts a
supervisor would otherwise have to discover by asking.

**Which claims here are verifiable, and which are merely asserted.** The
distinction is load-bearing and ORIGIN draws it explicitly rather than blurring it:

| Claim | Standing |
|---|---|
| Corpus membership within the MVCC horizon | **Verifiable** — read from storage history, not writable by application code |
| Corpus membership outside it | **Asserted** — application-maintained columns; `membership_as_of` reports which path answered so the answer can be weighed |
| Admission timestamp | **Verifiable** — the cluster's logical clock, taken inside the admitting transaction |
| Document integrity since admission | **Verifiable** — SHA-256 recorded at admission |
| Licence classification | **Asserted** — a machine's reading of a metadata string, and capable of being confidently wrong |
| That the declared use is truthful | **Neither** — `declared_use` is an unverified input. If it is wrong, every ruling downstream is wrong with it |

**Agreement between independent derivations is the evidentiary unit, not either
derivation alone.** `verify_integrity` exists because a record maintained by the
party being audited cannot corroborate itself. It does not prevent tampering; it
makes tampering visible, which is the achievable goal. Note that outside the GC
horizon it returns **inconclusive, and inconclusive is not a pass** — silence
there would be a false all-clear.

**The absence of a blocked build is not evidence of compliance.** `build_gates`
records allowed and blocked verdicts alike, so a corpus with no blocks either had
no violations or was never gated. Distinguishing those requires the gate history,
not the current state.

**What a supervisor would still have to request.** Nothing in the ledger
establishes that the corpus ORIGIN describes is the corpus the system actually
served from. That binding — ledger to deployed index — is outside ORIGIN's
boundary and would have to be evidenced separately. It is the first question
worth asking of any provenance claim, including this one.

---

## Where ORIGIN's evidence is unusually strong

Three claims that are hard to make about a conventional compliance tool, stated
so they can be attacked:

**1. The timestamp is not ours.** Admission time is CockroachDB's own logical
timestamp, taken inside the admitting transaction. An application-written
`created_at` is an assertion by the party being audited. A commit timestamp from a
linearizable distributed clock is a different category of artifact.

**2. The record resists its own author.** Most audit logs are written by the
system being audited and can be rewritten by it. `verify_integrity` cross-checks
the application-maintained columns against storage history that application code
cannot forge. It does not prevent tampering. It makes tampering *visible*, which
is the achievable goal.

**3. Deletion does not destroy the record.** A takedown is a soft delete
([`corpus.record_takedown`](src/origin/corpus.py:344)). Hard-deleting would
destroy the evidence the system exists to keep — and once garbage collection ran,
MVCC could not recover it either. The action that feels most like compliance
would actually defeat it.

---

## What ORIGIN does not do

Read this section before citing anything above.

**It is not a conformity assessment.** Art 43 conformity assessment, CE marking,
notified body involvement, the Art 47 declaration of conformity and Art 49
registration are all out of scope. ORIGIN produces evidence that would feed such
a process. It is not one.

**It performs no Fundamental Rights Impact Assessment.** Art 27 FRIA is an
assessment of impact on people. ORIGIN assesses provenance and rights in
documents. Wholly different exercise, no overlap.

**It does not classify the AI system's risk tier.** Whether a system is
prohibited, high-risk, limited-risk or minimal-risk under Art 5 / Annex III is a
legal determination about purpose and context. ORIGIN never asks. It takes
`declared_use` (`commercial` / `internal` / `research`) as an unverified input
from whoever created the corpus — and if that declaration is wrong, every ruling
downstream is wrong with it.

**It has no GDPR capability.** No personal-data detection, no lawful-basis
tracking, no DSAR handling, no Art 17 erasure workflow. A document can be fully
licensed and still unlawful to process. ORIGIN would pass it.

**Its licence classification is a machine's reading and can be wrong.** Novel
strings are classified by a language model. The provider seam is deliberate: an
unparseable response becomes `UNKNOWN` and therefore blocks
([`ledger.py:108`](src/origin/ledger.py:108)), so the failure mode is
inconvenience rather than exposure. But a *confidently incorrect* classification
is not caught by anything except a human, which is why
`confirm_determination` exists.

**The permitted-use matrix is not counsel's work.** It is a deliberately
conservative reading by an engineer. The classes are coarse; jurisdiction is not
modelled at all; "internal use at a commercial entity" is treated as arguable
rather than resolved. A real deployment replaces this matrix with one a lawyer
signs.

**Metadata is not the licence.** ORIGIN rules on the licence field a source
declares. It does not fetch and parse the actual `LICENSE` file, does not detect a
declaration contradicted by the terms it points to, and cannot see terms imposed
by contract rather than licence. It records when `cardData` and tags disagree
([`ingest/huggingface.py:80`](src/origin/ingest/huggingface.py:80)) — which is a
detection of *inconsistency*, not of *falsity*.

**Time travel has a real horizon.** Measured on a live CockroachDB Cloud cluster
(v26.2.5), MVCC reaches back roughly **4–5 hours**, not the 7 days configured in
`sql/002`. Resolving a table descriptor also reads system ranges, which keep their
own shorter TTL, and the usable horizon is the smaller of the two. Beyond it,
`membership_as_of` falls back to the bitemporal columns and *reports that it did*
— but `verify_integrity` then returns **inconclusive, which is not a pass**.

**It is scoped to text documents.** No images, audio, video, or code. Each
carries different licensing regimes.

---

## How this differs from the available AI Act tooling

The obvious question, and it deserves a direct answer rather than a claim of
novelty.

The tools that exist — the AI Act Explorer, the Compliance Checker, the
obligation matrices published by every large firm — are **questionnaires**. You
describe your system, and they tell you which obligations attach. They are
genuinely useful, they are free, and for a company that does not yet know
whether it is a provider or a deployer they are the right first stop.

They share one property: **every answer is an input you supplied about
yourself.** Nothing in them touches the data. A questionnaire cannot tell you
that eleven documents in your commercial corpus carry no licence at all, because
it never sees the corpus.

ORIGIN starts at the other end.

| | Questionnaire tools | ORIGIN |
|---|---|---|
| Input | What you say you are doing | What was actually admitted |
| Output | Which obligations attach | What the record can and cannot support |
| On uncertainty | Advises caution | **Blocks the build** and quotes the clause |
| Reproducible later | Re-answer the questions | Re-run against the same instant |
| Can be wrong about you | Only if you answer wrongly | Only if `declared_use` was wrong |

The two are complements, not competitors: the questionnaire tells you Article 53
applies to you; nothing in it produces the summary Article 53(1)(d) then requires
you to publish. That is the gap `origin article53` sits in.

Stated as plainly as it can be: **the checkers ask you what you did. ORIGIN reads
what you actually admitted, and reports where its own answer stops being
evidence.**

---

## Reading this as a governance artifact

If you are assessing ORIGIN as evidence of AI governance capability rather than
as software, the four things worth looking at are:

1. **[`licensing/policy.py`](src/origin/licensing/policy.py)** — the fail-closed
   default and the `REVIEW` outcome. The judgement is in what it declines to
   decide.
2. **[`corpus.verify_integrity`](src/origin/corpus.py:231)** — treating a single
   source of truth as insufficient, and reporting inconclusiveness rather than
   passing.
3. **The soft delete** — recognising that the most compliance-looking action
   destroys the compliance record.
4. **This section and the one above it** — the boundaries are stated in the same
   document as the claims.

---

## Sources

The regulatory position above was verified in August 2026. Primary sources should
be preferred over any of these summaries, and the AI Office template in particular
should be read directly rather than via commentary.

- [EU AI Act Omnibus Agreement — Postponed High-Risk Deadlines and Other Key Changes (Gibson Dunn)](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)
- [EU agrees to delay key AI Act compliance deadlines (Travers Smith)](https://www.traverssmith.com/knowledge/knowledge-container/eu-agrees-to-delay-key-ai-act-compliance-deadlines/)
- [Digital AI Omnibus Delays Key Deadlines, Introduces New Rules (Cooley)](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/)
- [The Digital AI Omnibus: Proposed deferral of high risk AI obligations (DLA Piper)](https://knowledge.dlapiper.com/dlapiperknowledge/globalemploymentlatestdevelopments/2026/The-Digital-AI-Omnibus-Proposed-deferral-of-high-risk-AI-obligations-under-the-AI-Act)
- [European Commission Releases Mandatory Template for Public Disclosure of AI Training Data (WilmerHale)](https://www.wilmerhale.com/en/insights/blogs/wilmerhale-privacy-and-cybersecurity-law/european-commission-releases-mandatory-template-for-public-disclosure-of-ai-training-data)
- [Decoding the GPAI Code of Practice and the Training Data Summary Template (Bird & Bird)](https://www.twobirds.com/en/insights/2025/taking-the-eu-ai-act-to-practice-decoding-the-gpai-code-of-practice-and-the-training-data-summary-te)
- [Copyright compliance under the EU AI Act for GPAI model providers (Clifford Chance)](https://www.cliffordchance.com/insights/resources/blogs/ip-insights/2025/10/copyright-compliance-under-the-eu-ai-act-for-gpai-model-providers.html)
- [EU AI Act Article 53: GPAI Provider Obligations (Legalithm)](https://www.legalithm.com/en/ai-act-guide/article-53)
