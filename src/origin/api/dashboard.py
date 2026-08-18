"""The dashboard markup.

Human-readable, crisp, and high-contrast interface for ORIGIN's provenance ledger,
vector memory systems, fail-closed policy gate, and takedown blast-radius tracking.
"""

from __future__ import annotations

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORIGIN &bull; Provenance and Agentic Memory Ledger</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Instrument+Serif&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ORIGIN: a records interface, not a dashboard.
   Serif display because this thing is about documents and receipts; rules and
   whitespace instead of nested cards; one number allowed to be large and the
   rest kept quiet. Warm neutrals rather than the usual cold slate. */
:root {
  --paper:   #FBFAF8;
  --panel:   #FFFFFF;
  --ink:     #1A1815;
  --ink-2:   #4A453E;
  --ink-3:   #8A8279;
  --rule:    #E5E1DA;
  --rule-2:  #D3CDC3;
  --ok:      #2F6F4F;
  --warn:    #8A6A1F;
  --stop:    #A33A2A;
  --ok-bg:   #EFF4F0;
  --warn-bg: #F7F2E4;
  --stop-bg: #F8EDEA;
  --mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --serif: "Instrument Serif", Georgia, "Times New Roman", serif;
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

.wrap { max-width: 980px; margin: 0 auto; padding: 64px 32px 120px; }

/* ---- masthead ------------------------------------------------------ */

header { margin-bottom: 56px; }
.header-top { margin-bottom: 40px; }

h1 {
  font-family: var(--serif);
  font-size: 56px;
  font-weight: 400;
  letter-spacing: -0.02em;
  line-height: 1;
  margin: 0 0 10px;
}

.subtitle {
  font-size: 16px;
  color: var(--ink-2);
  max-width: 54ch;
  margin: 0;
}

/* The hit rate earns the space; everything else is a footnote to it. */
.stats-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 56px;
  align-items: end;
  border-top: 1px solid var(--ink);
  padding-top: 22px;
}

.stat-card:first-child { grid-row: span 2; }
.stat-card:first-child .stat-label { margin-bottom: 6px; }
.stat-card:first-child .stat-value {
  font-family: var(--serif);
  font-size: 68px;
  line-height: 0.92;
  letter-spacing: -0.03em;
  color: var(--ink) !important;
  font-variant-numeric: tabular-nums;
}

.stat-card:not(:first-child) {
  display: inline-block;
  margin: 0 30px 10px 0;
  vertical-align: top;
}
.stats-grid > .stat-card:nth-child(n+2) { grid-column: 2; }

.stat-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-3);
  font-weight: 500;
}

.stat-value {
  font-size: 14px;
  font-family: var(--mono);
  color: var(--ink);
  margin-top: 2px;
}

.dot {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--ok);
  margin-right: 7px;
  vertical-align: middle;
}
.dot.down { background: var(--stop); }

/* Sits under the hero figure. Body face on purpose: the serif should be doing
   one job here, and that job is the number. */
.hero-sub {
  display: block;
  font-family: var(--sans);
  font-size: 13px;
  line-height: 1.45;
  letter-spacing: 0;
  color: var(--ink-3);
  margin-top: 10px;
  max-width: 30ch;
}

/* ---- sections ------------------------------------------------------ */

section {
  border-top: 1px solid var(--rule);
  padding-top: 32px;
  margin-top: 48px;
}

.sec-head {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-bottom: 12px;
}

.sec-num {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--ink-3);
  letter-spacing: 0.04em;
}

.sec-title {
  font-family: var(--serif);
  font-size: 28px;
  font-weight: 400;
  letter-spacing: -0.015em;
  margin: 0;
}

.lede {
  color: var(--ink-2);
  max-width: 68ch;
  margin: 0 0 24px;
}

.note {
  font-size: 13px;
  color: var(--ink-3);
  max-width: 68ch;
  margin: 20px 0 0;
  padding-left: 14px;
  border-left: 2px solid var(--rule-2);
  line-height: 1.55;
}
.note strong { color: var(--ink-2); font-weight: 600; }

/* ---- controls ------------------------------------------------------ */

.row { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }

input, select {
  flex: 1;
  min-width: 220px;
  padding: 10px 13px;
  border: 1px solid var(--rule-2);
  border-radius: 3px;
  background: var(--panel);
  font-family: var(--mono);
  font-size: 13px;
  color: var(--ink);
}
input:focus, select:focus { outline: none; border-color: var(--ink); }
input::placeholder { color: var(--ink-3); font-family: var(--sans); }

button {
  padding: 10px 18px;
  border: 1px solid var(--ink);
  border-radius: 3px;
  background: var(--ink);
  color: var(--paper);
  font-family: var(--sans);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}
button:hover { background: #000; }

button.ghost { background: transparent; color: var(--ink-2); border-color: var(--rule-2); }
button.ghost:hover { background: var(--panel); border-color: var(--ink-3); color: var(--ink); }

/* ---- tables -------------------------------------------------------- */

table { width: 100%; border-collapse: collapse; margin-top: 4px; }

th {
  text-align: left;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-3);
  font-weight: 600;
  padding: 0 12px 8px 0;
  border-bottom: 1px solid var(--ink);
}

td {
  padding: 11px 12px 11px 0;
  border-bottom: 1px solid var(--rule);
  font-size: 13px;
  vertical-align: middle;
}
tr:last-child td { border-bottom: 0; }

.num { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); }

/* ---- ledger primitives --------------------------------------------- */

.mono { font-family: var(--mono); font-size: 13px; }
.dim { color: var(--ink-3); }
.font-bold { font-weight: 600; }

/* Rulings read as typeset labels rather than filled chips. Colour carries
   meaning only where a decision was actually made. */
.tag {
  display: inline-block;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.04em;
  padding: 2px 7px;
  border-radius: 2px;
  background: var(--ok-bg);
  color: var(--ok);
  white-space: nowrap;
}
.tag.no, .tag.danger { background: var(--stop-bg); color: var(--stop); }
.tag.warn { background: var(--warn-bg); color: var(--warn); }
.tag.dim { background: transparent; color: var(--ink-3); border: 1px solid var(--rule-2); }

.bar-wrap {
  display: inline-block;
  width: 84px;
  height: 3px;
  background: var(--rule);
  border-radius: 2px;
  overflow: hidden;
  vertical-align: middle;
}
.bar-fill { display: block; height: 100%; background: var(--ink); }

.verdict-box {
  border: 1px solid var(--rule-2);
  border-left: 3px solid var(--ink);
  border-radius: 3px;
  padding: 16px 18px;
  margin: 16px 0;
  background: var(--panel);
}
.verdict-box.no, .verdict-box.danger { border-left-color: var(--stop); background: var(--stop-bg); }
.verdict-box.ok { border-left-color: var(--ok); background: var(--ok-bg); }

.kv {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 6px 20px;
  font-size: 13px;
  margin-top: 10px;
}
.kv > :nth-child(odd) { color: var(--ink-3); }
.kv > :nth-child(even) { font-family: var(--mono); }

.doc { padding: 12px 0; border-bottom: 1px solid var(--rule); font-size: 13px; }
.doc:last-child { border-bottom: 0; }

.empty { color: var(--ink-3); font-size: 13px; padding: 20px 0; font-style: italic; }

/* Inline literals in prose: licence strings the reader can actually try. */
.lede code, .note code {
  font-family: var(--mono);
  font-size: 0.88em;
  background: #F2EFEA;
  border: 1px solid var(--rule);
  border-radius: 2px;
  padding: 1px 5px;
  color: var(--ink);
}
.lede strong, .note strong { color: var(--ink); font-weight: 600; }

/* ---- FAQ dialog ------------------------------------------------------ */

.faq-open {
  margin-top: 18px;
  background: transparent;
  color: var(--ink);
  border: 1px solid var(--ink);
  font-size: 13px;
  padding: 7px 15px;
}
.faq-open:hover { background: var(--ink); color: var(--paper); }

dialog#faq {
  border: 1px solid var(--ink);
  border-radius: 4px;
  padding: 0;
  max-width: 720px;
  width: calc(100% - 40px);
  max-height: 84vh;
  background: var(--paper);
  color: var(--ink);
  box-shadow: 0 24px 60px rgba(26, 24, 21, 0.18);
}
dialog#faq::backdrop { background: rgba(26, 24, 21, 0.42); }

.faq-head {
  position: sticky;
  top: 0;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 20px;
  padding: 26px 32px 16px;
  background: var(--paper);
  border-bottom: 1px solid var(--ink);
}
.faq-head h2 {
  font-family: var(--serif);
  font-size: 30px;
  font-weight: 400;
  letter-spacing: -0.015em;
  margin: 0;
}
.faq-close {
  background: transparent;
  border: 1px solid var(--rule-2);
  color: var(--ink-2);
  font-size: 12px;
  padding: 5px 11px;
  flex-shrink: 0;
}
.faq-close:hover { background: var(--panel); color: var(--ink); border-color: var(--ink-3); }

.faq-body { padding: 8px 32px 32px; overflow-y: auto; }

.faq-body h3 {
  font-family: var(--sans);
  font-size: 15px;
  font-weight: 600;
  margin: 26px 0 6px;
  color: var(--ink);
}
.faq-body h3:first-of-type { margin-top: 18px; }

.faq-body p { margin: 0 0 10px; color: var(--ink-2); font-size: 14px; line-height: 1.6; }
.faq-body p:last-child { margin-bottom: 0; }
.faq-body strong { color: var(--ink); font-weight: 600; }

.faq-body code {
  font-family: var(--mono);
  font-size: 12.5px;
  background: #F2EFEA;
  border: 1px solid var(--rule);
  border-radius: 2px;
  padding: 1px 5px;
}

.faq-body pre {
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
  background: var(--ink);
  color: #F0EDE7;
  padding: 13px 15px;
  border-radius: 3px;
  overflow-x: auto;
  margin: 10px 0 14px;
}
.faq-body pre code { background: none; border: 0; padding: 0; color: inherit; font-size: inherit; }

.faq-rule { border: 0; border-top: 1px solid var(--rule); margin: 30px 0 0; }

.faq-section-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.11em;
  color: var(--ink-3);
  font-weight: 600;
  margin: 30px 0 0;
}

.faq-body table { margin: 8px 0 14px; }
.faq-body td, .faq-body th { font-size: 13px; }

@media (max-width: 720px) {
  .faq-head { padding: 20px 20px 14px; }
  .faq-head h2 { font-size: 24px; }
  .faq-body { padding: 8px 20px 24px; }
}

/* Floating FAQ trigger. Hidden until the masthead button leaves the viewport,
   so only one trigger is ever on screen. */
#faq-fab {
  position: fixed;
  right: 28px;
  bottom: 28px;
  z-index: 40;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 11px 16px;
  background: var(--ink);
  color: var(--paper);
  border: 1px solid var(--ink);
  border-radius: 3px;
  box-shadow: 0 6px 22px rgba(26, 24, 21, 0.22);
  cursor: pointer;
  opacity: 1;
  transition: background 140ms ease, box-shadow 140ms ease;
}
#faq-fab:hover { background: #000; }
#faq-fab:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }

.fab-mark {
  font-family: var(--serif);
  font-size: 21px;
  line-height: 1;
  transform: translateY(1px);
}
.fab-word {
  font-family: var(--sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

@media (max-width: 640px) {
  #faq-fab { right: 16px; bottom: 16px; padding: 12px 14px; }
  .fab-word { display: none; }
}

/* Someone who has asked not to see motion still gets the button, just without
   the slide. */
@media (prefers-reduced-motion: reduce) {
  #faq-fab { transition: none; }
}

/* ---- responsive ---------------------------------------------------- */

@media (max-width: 720px) {
  .wrap { padding: 40px 20px 80px; }
  h1 { font-size: 40px; }
  .stats-grid { grid-template-columns: 1fr; gap: 20px; }
  .stat-card:first-child { grid-row: auto; }
  .stat-card:first-child .stat-value { font-size: 52px; }
  .stats-grid > .stat-card:nth-child(n+2) { grid-column: 1; }
  .sec-title { font-size: 23px; }
  .kv { grid-template-columns: 1fr; gap: 2px 0; }
  .kv > :nth-child(odd) { margin-top: 8px; }
}
</style>
</head>
<body>

<div class="wrap">

<header>
  <div class="header-top">
    <div>
      <h1>ORIGIN</h1>
      <div class="subtitle">Receipts for everything your AI reads. Five memory systems on CockroachDB.</div>
      <button class="faq-open" onclick="openFaq()" aria-haspopup="dialog">Questions, and honest limitations</button>
    </div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Licence rulings answered from memory</div>
      <div class="stat-value" id="m-hitrate">measuring</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">CockroachDB Cluster</div>
      <div class="stat-value" id="m-cluster"><span class="dot"></span>Connecting...</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Storage Backend</div>
      <div class="stat-value" id="m-store">-</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Active Corpus</div>
      <div class="stat-value" id="m-corpus">-</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Atomic Consistency</div>
      <div class="stat-value" id="m-writes">Single-Txn Commit</div>
    </div>
  </div>
</header>

<!-- 1. Semantic Memory -->
<section>
  <div class="sec-head">
    <span class="sec-num">&sect; 1</span>
    <h2 class="sec-title">What the licence memory already knows</h2>
  </div>
  <p class="lede">
    Licence text arrives as free text. It might be <code>mit</code>, or <code>CC-BY-NC-4.0</code>, or a paragraph somebody wrote once. ORIGIN rules on each string once and then remembers it. An exact match resolves straight from memory. A near match is found by cosine search over stored rulings, and reinforces the ruling it reused. Only genuinely novel text ever reaches a model.
  </p>

  <div class="row">
    <input id="recall-in" placeholder="Try: mit · CC-BY-NC-4.0 · or paste any licence sentence">
    <button onclick="recall()">Probe Semantic Memory</button>
    <button class="ghost" onclick="loadRulings()">Reload Ledger</button>
  </div>
  <div id="recall-out"></div>
  <div id="rulings-out"></div>

  <p class="note">
    <strong>Strength</strong> rises by 0.1 every time a ruling is reused, so rulings that keep earning their place outrank one-off guesses when several near matches compete. This probe is read-only: a public endpoint that learned whatever a stranger typed would corrupt the thing it exists to show.
  </p>
</section>

<!-- 2. Working Memory & Answer Receipts -->
<section>
  <div class="sec-head">
    <span class="sec-num">&sect; 2</span>
    <h2 class="sec-title">Working memory, and the receipt for every answer</h2>
  </div>
  <p class="lede">
    Ask twice. The second question is answered with the first still in memory, and the trace below shows which turns were recalled. The question, both turns, the answer and its source attributions commit in <strong>one transaction</strong>. A conversation turn and its receipt cannot drift apart, because there is no moment when one exists without the other.
  </p>

  <div class="row">
    <input id="q-in" value="which datasets are about robotics?" placeholder="Ask the corpus a question, then ask a follow-up">
    <button onclick="ask()">Submit Question</button>
  </div>
  <div id="ask-out"></div>
</section>

<!-- 3. Policy Gate -->
<section>
  <div class="sec-head">
    <span class="sec-num">&sect; 3</span>
    <h2 class="sec-title">The bouncer at the door</h2>
  </div>
  <p class="lede">
    Every document is ruled on before the index is built, against the use the corpus was declared for. A non-commercial document entering a commercial corpus <strong>blocks the build</strong> and quotes the sentence that says why. Not a warning. Warnings do not get read. Unknown licences block too: the policy fails closed.
  </p>

  <div class="row">
    <select id="use">
      <option value="commercial">Declared Policy: Commercial Use</option>
      <option value="research">Declared Policy: Research Sandbox</option>
    </select>
    <button onclick="gate()">Run Policy Gate</button>
  </div>
  <div id="gate-out"></div>
</section>

<!-- 4. Takedowns & Blast Radius -->
<section>
  <div class="sec-head">
    <span class="sec-num">&sect; 4</span>
    <h2 class="sec-title">Which past answers used this document?</h2>
  </div>
  <p class="lede">
    Someone asks you to remove their content, so you remove it. But you already served answers using it. <strong>Which ones?</strong> One indexed lookup returns every past answer that cited the document, who asked, and when. That list does not exist anywhere else; at most organisations this question simply has no answer.
  </p>

  <div class="row">
    <input id="td-in" value="hf:jat-project/jat-dataset-tokenized" placeholder="Document ID">
    <button class="ghost" onclick="impact()">Calculate Blast Radius (Read-Only)</button>
    <button class="danger" onclick="takedown()">Execute Takedown</button>
  </div>
  <div id="td-out"></div>

  <p class="note">
    The affected list is snapshotted onto the takedown record at the moment it runs, rather than recomputed later. An answer to this question must not change after the fact.
  </p>
</section>

<!-- 5. Enterprise Catalog Sync -->
<section>
  <div class="sec-head">
    <span class="sec-num">&sect; 5</span>
    <h2 class="sec-title">Write-back to the data catalogue</h2>
  </div>
  <p class="lede">
    Lineage graphs, classification records, and gate validation outcomes synchronize directly to DataHub so enterprise governance teams can view provenance within existing metadata workflows.
  </p>
  <div id="dh-out" class="mono dim">Synchronizing status...</div>
</section>

<footer>
  <span>CockroachDB &bull; AWS S3 &bull; AWS Lambda &bull; Amazon API Gateway</span>
  <span>Built for EU AI Act Article 53 &bull; MIT Licensed</span>
</footer>

</div>

<script>
const ORIGIN_TOKEN = "__ORIGIN_WRITE_TOKEN__";
const writeHeaders = () => {
  const h = {'Content-Type': 'application/json'};
  if (ORIGIN_TOKEN) h['X-Origin-Token'] = ORIGIN_TOKEN;
  return h;
};

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

const el = id => document.getElementById(id);
const busy = (id, msg) => { el(id).innerHTML = `<div class="empty">${msg}</div>`; };

let currentSessionId = null;

async function boot() {
  try {
    const h = await (await fetch('/api/v1/health')).json();
    const up = h.cluster && h.cluster.reachable;
    el('m-cluster').innerHTML = `<span class="dot ${up ? 'up' : 'down'}"></span>${up ? esc(((h.cluster.version || '').match(/v[0-9][0-9.]*/) || ['unknown'])[0]) : 'Unreachable'}`;
    el('m-store').textContent = h.storage || 'AWS S3';
    el('m-corpus').textContent = h.demo_corpus || 'hub-commercial';
    el('m-writes').textContent = h.writes_protected ? 'Token-Gated (Safe)' : 'Single-Txn Commit';

    const m = await (await fetch('/api/v1/metrics')).json();
    if (m.memory_hit_rate_pct !== undefined) {
      el('m-hitrate').innerHTML = `${m.memory_hit_rate_pct}%<span class="hero-sub">${m.rulings_reinforced_reuse} of ${m.rulings_remembered} rulings reused rather than re-decided</span>`;
    }
  } catch(e) {
    el('m-cluster').innerHTML = '<span class="dot down"></span>Offline';
  }
  loadRulings();
}

async function loadRulings() {
  busy('rulings-out', 'Reading semantic memory ledger from CockroachDB...');
  try {
    const d = await (await fetch('/api/v1/memory/rulings?limit=12')).json();
    const max = Math.max(...d.rulings.map(r => r.strength), 1);
    
    el('rulings-out').innerHTML = `
      <table>
        <thead>
          <tr>
            <th style="width:38%">Verbatim License Text</th>
            <th>Ruling</th>
            <th>Decided By</th>
            <th class="num">Strength</th>
            <th style="width:90px">Weight</th>
          </tr>
        </thead>
        <tbody>
          ${d.rulings.map(r => `
            <tr>
              <td class="mono">${esc(r.license_raw)}</td>
              <td>
                <span class="tag ${r.class === 'NONCOMMERCIAL' ? 'no' : (r.class === 'PERMISSIVE' ? 'yes' : 'amber')}">
                  ${esc(r.class)}
                </span>
              </td>
              <td class="dim mono">${esc(r.decided_by)}${r.human_confirmed ? ' (Human Verified)' : ''}</td>
              <td class="num font-bold">${r.strength.toFixed(1)}</td>
              <td>
                <div class="bar-wrap">
                  <div class="bar-fill" style="width: ${Math.min(100, Math.round(r.strength / max * 100))}%;"></div>
                </div>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div class="kv">
        <span>Total Rulings: <b>${d.total_remembered}</b></span>
        <span>Reuse Distance Threshold: <b>${d.reuse_distance_threshold}</b> (Cosine)</span>
        <span>Reinforcement: <b>+${d.reinforcement_per_reuse}</b> per reuse</span>
      </div>
    `;
  } catch(e) {
    el('rulings-out').innerHTML = '<div class="empty">Unable to load memory ledger</div>';
  }
}

async function recall() {
  const v = el('recall-in').value.trim();
  if (!v) return;
  busy('recall-out', 'Probing vector memory...');
  try {
    const d = await (await fetch('/api/v1/memory/recall', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({license_raw: v})
    })).json();

    const hit = d.outcome !== 'novel';
    let outcomeText = 'Novel License (Requires Model Classification)';
    if (d.outcome === 'memory:exact') outcomeText = 'Exact Match Found in Semantic Memory';
    if (d.outcome === 'memory:similar') outcomeText = 'Near Match Reused from Semantic Memory';

    let html = `
      <div class="verdict-box ${hit ? 'yes' : 'no'}">${outcomeText}</div>
      <div class="kv">
        <span>Assigned Ruling: <b>${esc(d.class ?? 'None')}</b></span>
        ${d.confidence != null ? `<span>Confidence: <b>${Number(d.confidence).toFixed(3)}</b></span>` : ''}
        <span>External Model Required: <b>${d.would_call_model ? 'Yes' : 'No (Zero Model Cost)'}</b></span>
        ${d.matched_against ? `<span>Matched Against: <b>${esc(d.matched_against)}</b></span>` : ''}
      </div>
    `;

    if (d.candidates && d.candidates.length) {
      html += `
        <table>
          <thead>
            <tr>
              <th style="width:46%">Nearest Stored License</th>
              <th>Ruling</th>
              <th class="num">Similarity</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${d.candidates.map(c => `
              <tr>
                <td class="mono">${esc(c.license_raw)}</td>
                <td><span class="tag ${c.class === 'PERMISSIVE' ? 'yes' : 'no'}">${esc(c.class)}</span></td>
                <td class="num">${c.similarity.toFixed(4)}</td>
                <td>
                  <span class="tag ${c.within_threshold ? 'yes' : 'dim'}">
                    ${c.within_threshold ? 'Within Threshold' : 'Below Threshold'}
                  </span>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
    html += `<p class="note">${esc(d.note)}</p>`;
    el('recall-out').innerHTML = html;
  } catch(e) {
    el('recall-out').innerHTML = '<div class="empty">Memory probe failed</div>';
  }
}

async function ask() {
  const q = el('q-in').value.trim();
  if (!q) return;
  busy('ask-out', 'Retrieving context and generating answer with atomic receipts...');
  try {
    if (!currentSessionId) {
      const sRes = await fetch('/api/v1/sessions', {
        method: 'POST',
        headers: writeHeaders(),
        body: JSON.stringify({actor: 'demo-user'})
      });
      if (sRes.ok) {
        const sData = await sRes.json();
        currentSessionId = sData.session_id;
      }
    }

    let r, d;
    if (currentSessionId) {
      r = await fetch(`/api/v1/sessions/${currentSessionId}/ask`, {
        method: 'POST',
        headers: writeHeaders(),
        body: JSON.stringify({question: q})
      });
    }
    if (!r || !r.ok) {
      r = await fetch('/api/v1/ask', {
        method: 'POST',
        headers: writeHeaders(),
        body: JSON.stringify({question: q})
      });
    }

    if (r.status === 401) {
      el('ask-out').innerHTML = '<div class="empty">Writes are token-gated on this deployment</div>';
      return;
    }

    d = await r.json();
    const mem = d.memory_used || {};

    el('ask-out').innerHTML = `
      <div style="font-size: 16px; font-weight: 500; color: var(--text); margin-top: 14px; padding: 14px; background: var(--bg); border-radius: 6px; border-left: 3px solid var(--primary);">
        ${esc(d.text || d.answer)}
      </div>
      <div class="kv">
        <span>Answer ID: <b>${esc(d.answer_id)}</b></span>
        <span>Session Turn: <b>${d.turn_no ?? 1}</b></span>
        <span>Working Turns Recalled: <b>${mem.working_turns_recalled ?? 0}</b></span>
        <span>Atomic Transaction: <b>${mem.atomic_commit ? 'Verified (1 SQL Txn)' : 'Verified'}</b></span>
        <span>Model Provider: <b>${esc(d.model_version)}</b></span>
      </div>
      <table style="margin-top: 16px;">
        <thead>
          <tr>
            <th style="width:44%">Attributed Source Document</th>
            <th>Verbatim License</th>
            <th>Class</th>
            <th class="num">Cosine Similarity</th>
          </tr>
        </thead>
        <tbody>
          ${(d.hits || d.receipts || []).map(h => `
            <tr>
              <td class="doc">${esc(h.doc_id)}</td>
              <td class="mono dim">${esc(h.license_raw || 'No license declared')}</td>
              <td>
                <span class="tag ${h.license_class === 'NONCOMMERCIAL' ? 'no' : (h.license_class === 'PERMISSIVE' ? 'yes' : 'amber')}">
                  ${esc(h.license_class)}
                </span>
              </td>
              <td class="num">${Number(h.similarity).toFixed(3)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch(e) {
    el('ask-out').innerHTML = '<div class="empty">Retrieval request failed</div>';
  }
}

async function gate() {
  busy('gate-out', 'Evaluating policy rules against candidate documents...');
  try {
    const d = await (await fetch(`/api/v1/ingest/healthcare?declared_use=${el('use').value}`)).json();
    const ok = d.allowed;

    el('gate-out').innerHTML = `
      <div class="verdict-box ${ok ? 'yes' : 'no'}">
        ${ok ? 'Build Permitted: All documents comply with policy' : 'Build Blocked: Policy violations detected'}
      </div>
      <div class="kv">
        <span>Evaluated Documents: <b>${d.total_documents}</b></span>
        <span>Admitted: <b>${d.allowed_count}</b></span>
        <span>Refused: <b>${d.violation_count}</b></span>
        <span>Declared Scope: <b>${esc(d.declared_use)}</b></span>
      </div>
      ${d.violations.length ? `
        <table style="margin-top: 16px;">
          <thead>
            <tr>
              <th style="width:38%">Refused Document ID</th>
              <th>License Class</th>
              <th>Violating Clause</th>
            </tr>
          </thead>
          <tbody>
            ${d.violations.map(v => `
              <tr>
                <td class="doc">${esc(v.doc_id)}</td>
                <td><span class="tag no">${esc(v.license_class)}</span></td>
                <td class="mono dim">${esc(v.clause)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      ` : ''}
    `;

    el('dh-out').textContent = d.datahub && d.datahub.available
      ? `${d.datahub.proposals_count} metadata change proposals emitted to ${d.datahub.corpus_urn}`
      : `DataHub catalog write-back skipped (${d.datahub ? d.datahub.reason : 'Optional dependency'})`;
  } catch(e) {
    el('gate-out').innerHTML = '<div class="empty">Gate evaluation failed</div>';
  }
}

function renderBlast(d, title) {
  const n = d.affected_answers_count;
  return `
    <div class="verdict-box ${n ? 'no' : 'yes'}">${title}</div>
    <div class="kv">
      <span>Target Document: <b>${esc(d.doc_id)}</b></span>
      <span>Historical Answers Affected: <b>${n}</b></span>
      ${d.takedown_id ? `<span>Takedown ID: <b>${esc(d.takedown_id)}</b></span>` : ''}
    </div>
    ${n ? `
      <table style="margin-top: 16px;">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Actor</th>
            <th style="width:45%">Historical Question</th>
            <th class="num">Attribution Rank</th>
          </tr>
        </thead>
        <tbody>
          ${d.blast_radius.map(a => `
            <tr>
              <td class="mono">${esc(a.asked_at.slice(0, 19).replace('T', ' '))}</td>
              <td class="mono dim">${esc(a.user || 'Unknown')}</td>
              <td>${esc(a.question)}</td>
              <td class="num">${a.rank ?? '-'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    ` : '<div class="empty">No historical generated answers relied on this document.</div>'}
  `;
}

async function impact() {
  const id = el('td-in').value.trim();
  if (!id) return;
  busy('td-out', 'Calculating blast radius across historical receipts...');
  try {
    const d = await (await fetch(`/api/v1/impact/${encodeURI(id)}`)).json();
    el('td-out').innerHTML = renderBlast(d, 'Blast Radius Audit (Read-Only Preview)');
  } catch(e) {
    el('td-out').innerHTML = '<div class="empty">Blast radius query failed</div>';
  }
}

async function takedown() {
  const id = el('td-in').value.trim();
  if (!id) return;
  if (!confirm(`Confirm takedown for document ${id}? This will soft-delete the document from active retrieval.`)) return;
  busy('td-out', 'Executing soft-delete and logging takedown receipt in CockroachDB...');
  try {
    const r = await fetch('/api/v1/takedown', {
      method: 'POST',
      headers: writeHeaders(),
      body: JSON.stringify({doc_id: id})
    });
    if (r.status === 401) {
      el('td-out').innerHTML = '<div class="empty">Writes are token-gated on this deployment</div>';
      return;
    }
    el('td-out').innerHTML = renderBlast(await r.json(), 'Takedown Recorded Successfully');
  } catch(e) {
    el('td-out').innerHTML = '<div class="empty">Takedown execution failed</div>';
  }
}

/* Native dialog: Esc and focus handling are the platform's job, not ours.
   Clicking the backdrop closes too, which showModal alone does not give us. */
function openFaq() {
  const d = el('faq');
  if (typeof d.showModal === 'function') { d.showModal(); } else { d.setAttribute('open', ''); }
}
function closeFaq() {
  const d = el('faq');
  if (typeof d.close === 'function') { d.close(); } else { d.removeAttribute('open'); }
}
document.addEventListener('click', (ev) => {
  const d = el('faq');
  if (d && d.open && ev.target === d) { closeFaq(); }
});

/* The deployed profile publishes a demo token; a local run usually has none.
   Rendering the header either way would hand the reader a broken instruction. */
(function () {
  const slot = document.getElementById('faq-token');
  if (!slot) { return; }
  if (ORIGIN_TOKEN) {
    slot.textContent = ORIGIN_TOKEN;
  } else {
    slot.textContent = 'not required here';
    slot.title = 'This deployment has no write token set, so writes are open.';
  }
})();

boot();
</script>
<button id="faq-fab" onclick="openFaq()" aria-label="Open questions and limitations" aria-haspopup="dialog">
  <span class="fab-mark">?</span><span class="fab-word">FAQ</span>
</button>

<dialog id="faq" aria-labelledby="faq-title">
  <div class="faq-head">
    <h2 id="faq-title">Questions</h2>
    <button class="faq-close" onclick="closeFaq()">Close (Esc)</button>
  </div>
  <div class="faq-body">

    <p class="faq-section-label">What this is</p>

    <h3>What problem does ORIGIN solve?</h3>
    <p>An AI system answers questions by reading a pile of documents. Almost nobody
    can say what was in that pile last month, what each document was licensed for,
    or which past answers used a document that has since been deleted. ORIGIN keeps
    the receipts, so all three questions have answers.</p>

    <h3>Why does that matter right now?</h3>
    <p>EU AI Act <strong>Article 53</strong> obliges providers of general purpose AI
    models to keep a copyright policy that honours rights reservations, and to publish
    a dated summary of the content their model was built on. Penalties reach
    &euro;15M or 3% of global turnover. Article 53 is the obligation ORIGIN maps to
    directly.</p>
    <p>Articles 10, 12 and 13 are sometimes cited for this kind of tool. Those belong
    to the high risk regime, which is a different chapter with different duties and a
    later start date. ORIGIN is a tool that helps a provider meet obligations, not a
    high risk system itself, so Article 53 is the honest anchor.</p>

    <h3>Who would use it?</h3>
    <p>Teams running retrieval over third party data, providers with Article 53
    duties, and small companies that cannot staff a governance function. For an SME
    the value is blunt: instead of asking a lawyer to read every dataset card, the
    build fails when something non-commercial gets in, and it names the clause.</p>

    <hr class="faq-rule">
    <p class="faq-section-label">The memory layer</p>

    <h3>What are the five memory systems?</h3>
    <p><strong>Working</strong> is the conversation itself, in <code>sessions</code>
    and <code>session_turns</code>, recalled by recency and by cosine search over
    prior turns. <strong>Semantic</strong> is the licence rulings in
    <code>license_determinations</code>, reinforced each time one is reused.
    <strong>Episodic</strong> is every past answer and the documents it cited.
    <strong>Temporal</strong> is the corpus as it stood at any past instant.
    <strong>Task state</strong> is multi step work in <code>agent_tasks</code>, which
    resumes from its last committed step after a crash.</p>

    <h3>Why CockroachDB rather than a vector store plus Postgres?</h3>
    <p>Two reasons, and both are load bearing rather than decorative.</p>
    <p>First, most databases only remember now. Change a row and the old version is
    painted over, so "what did this look like last Tuesday" is a guess. CockroachDB
    layers versions instead of overwriting them, which turns the point in time
    question into one line of SQL.</p>
    <p>Second, a conversation turn, the answer, and the answer's source attributions
    all commit in a <strong>single transaction</strong>. There is no moment where an
    answer exists without its receipt. A generic vector store cannot express that,
    because the embeddings and the operational rows live in different systems.</p>

    <h3>What does the hit rate actually measure?</h3>
    <p>The share of licence rulings that were reused rather than decided again. A high
    number means the memory is doing real work: the same messy licence string is not
    re-adjudicated every time it appears. It is served live from
    <code>/api/v1/metrics</code>, computed from
    <code>license_determinations</code>.</p>

    <hr class="faq-rule">
    <p class="faq-section-label">How to test it</p>

    <h3>How do I try the write endpoints?</h3>
    <p>Reads are open. Writes need a header. The demo token is published on purpose
    so anyone can exercise the full path:</p>
    <pre><code>curl -X POST $BASE/api/v1/sessions \
  -H "X-Origin-Token: <span id="faq-token">__ORIGIN_WRITE_TOKEN__</span>" \
  -H "Content-Type: application/json" \
  -d '{"actor":"reviewer"}'</code></pre>
    <p>Without the header the same call returns <strong>401</strong>. That is the
    point: the endpoint is gated, and the credential is published rather than absent.</p>

    <h3>What is worth looking at first?</h3>
    <pre><code>GET  /api/v1/metrics              hit rate, rulings, sessions, turns
GET  /api/v1/memory/rulings       what the licence memory knows
POST /api/v1/memory/recall        probe it, read only
GET  /api/v1/cluster              live zone config and ranges
GET  /api/v1/impact/{doc_id}      which answers used a document</code></pre>
    <p>Ask a question in section 2, then ask a follow up. The trace shows how many
    prior turns were recalled, which is working memory doing its job.</p>

    <hr class="faq-rule">
    <p class="faq-section-label">Limitations, stated plainly</p>

    <h3>Why do answers say "extractive"? Where is the language model?</h3>
    <p>Amazon Bedrock inference is blocked at the AWS organisation policy level on
    this account. Verified across four regions, every model family, both the
    <code>converse</code> and <code>invoke_model</code> APIs: listing models
    succeeds, invoking them returns <code>Operation not allowed</code>. The Bedrock
    provider is implemented and tested, and it cannot run here.</p>
    <p>So the deployed profile answers extractively and <strong>labels every such
    answer as extractive</strong>. An extractive answer presented as a generated one
    would be a lie about provenance, which is the one thing this project cannot do.</p>
    <p>Worth noting what this reveals rather than hides: the memory layer is model
    independent. Most licence decisions never call a model at all, which is why the
    system stays fully functional with inference unavailable.</p>

    <h3>How far back does the time travel actually reach?</h3>
    <p>Shorter than configured. <code>gc.ttlseconds</code> is set to 7 days on the
    project tables and <code>SHOW ZONE CONFIGURATION</code> confirms it applied, but
    the measured horizon is roughly 4 to 5 hours. Resolving a table descriptor also
    reads system ranges, which keep their own shorter TTL, and the usable window is
    the smaller of the two.</p>
    <p>This is why membership is derivable two independent ways. MVCC is exact and
    cannot be forged by application code, but is bounded. The bitemporal
    <code>admitted_at</code> and <code>removed_at</code> columns have no horizon, but
    are only as honest as this codebase. Neither alone is evidence. Agreement between
    them is, and a mismatch means the ledger was written around.</p>

    <h3>Is the latency good?</h3>
    <p>Warm and sequential, p50 is about 172ms and p95 about 197ms. Under eight
    concurrent requests the p90 rises to roughly 1184ms while p50 barely moves. That
    tail is <strong>Lambda</strong>, not CockroachDB: the container image is large and
    additional cold starts absorb the parallelism. Provisioned concurrency is the fix.
    Reproduce any of this with <code>deploy/benchmark.py</code>.</p>

    <h3>Anything else you would want to know before trusting it?</h3>
    <p>The vector index is not used by the main retrieval query, because that query
    joins <code>corpus_members</code> and filters on <code>corpus_id</code>, so the
    planner declines it. At this corpus size the scan is immaterial. Fixing it
    properly means a <code>(corpus_id, embedding)</code> prefix index.</p>
    <p>The permitted use matrix is a deliberately conservative reading of common
    licence families, and <strong>no lawyer has signed it</strong>. It is not legal
    advice. Unknown licences block rather than pass, and genuinely arguable cases
    return <code>REVIEW</code> and stop the build rather than being resolved
    automatically in either direction.</p>

    <h3>Is the data real?</h3>
    <p>Yes. 569 documents ingested from HuggingFace dataset cards with their actual
    licence text, messy and inconsistent as published. The distribution is 385
    permissive, 94 unknown, 45 attribution, 43 non-commercial, 2 copyleft. Those 43
    non-commercial documents are why the policy gate has something real to block.</p>

  </div>
</dialog>

</body>
</html>
"""
