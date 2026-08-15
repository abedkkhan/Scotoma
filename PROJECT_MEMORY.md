# Scotoma — Project Memory

## Mission

Scotoma measures what an AI agent did **not** investigate before reaching a
conclusion about a codebase.

The product is not another coding agent. It is a vendor-neutral audit and
measurement layer for agents such as Codex, Claude Code, Cursor, and small
reference agents. Its analogue is code coverage: code coverage identifies what
tests did not execute; Scotoma identifies what an agent did not examine before
making a claim.

## Core Problem

An agent can inspect 6 files in a 200-file repository and confidently report
that it found no SQL injection vulnerabilities. Existing systems do not clearly
distinguish:

- "I investigated the relevant territory and found no vulnerability."
- "I found no vulnerability in the small portion I happened to inspect."

Simple file-read counts do not solve this. Six files may contain nearly all of
the evidence relevant to a question, while fifty inspected files may be
irrelevant. Scotoma must measure the relevance of examined and unexamined
territory, not merely count files.

## Core Metric

**Risk-Weighted Coverage (RWC)**

```text
RWC = relevance mass examined / total relevance mass in the repository
```

The complementary blind-spot score is:

```text
blind-spot mass = relevance mass unexamined / total relevance mass
```

The first prototype will estimate each unexamined unit's overturn risk from a
combination of:

```text
relevance(unit) = 0.40×semantic + 0.25×structural + 0.35×lexical

blind_risk(unit) = relevance(unit) × (1 - examination_depth)
```

These are estimates, not mathematical proof. Scotoma ranks likely blind spots
and measures the evidentiary basis of a conclusion; it must not claim to know
every omitted risk.

## Three Measurement Layers

1. **Exploration coverage** — which repository units were inspected?
2. **Evidence coverage** — which inspected units support each conclusion?
3. **Overturn risk** — which uninspected units are most likely to invalidate or
   materially change the conclusion?

## Demo Contract

The primary demo asks an agent whether a repository contains SQL injection
risks.

1. The agent examines several files and reports no vulnerability.
2. Scotoma ingests the agent trace.
3. Scotoma reports low risk-weighted coverage despite high claimed confidence.
4. It ranks an unread route or database file as the highest-risk blind spot.
5. Inspecting that file reveals a real SQL injection vulnerability.
6. The agent revises its conclusion and measured coverage increases.

Illustrative output:

```text
Conclusion: No SQL injection found
Confidence claimed: High
Evidence coverage: 18%
Conclusion stability: Low

Highest-risk blind spots:
1. src/routes/search.ts       94%
2. src/db/rawQueries.ts       89%
3. src/legacy/importer.ts     71%
```

## Architecture

```text
Agent trace
    ↓
Vendor adapter
    ↓
Normalized events
    ↓
Repository territory index + dependency graph
    ↓
Claim/evidence mapper
    ↓
Risk-Weighted Coverage engine
    ↓
Terminal and HTML coverage report
```

The metric engine is the central intellectual property and must remain
independent of transcript format. A deterministic reference agent guarantees a
reliable demo; real Codex/Claude transcript adapters are optional headline
inputs.

## Three-Hour Build Plan

| Step | Deliverable | Target |
|---|---|---:|
| 1 | Scaffold and repository territory indexer; no AI | 0:20 |
| 2 | Instrumented reference agent producing normalized traces | 1:00 |
| 3 | Risk-Weighted Coverage ranking engine | 1:40 |
| 4 | LLM adjudication and conclusion flip test | complete |
| 5 | Rich terminal report and dark-map HTML visualization | next |
| 6 | Demo rehearsal and pitch | final |

## Step 1 Contract: Territory Index

Build a Python package with `build_index(repo_path: str) -> dict`. It returns
one unit per eligible source file with:

- `path`: repository-relative path
- `language`: inferred language
- `size_bytes`: file size
- `loc`: nonblank line count
- `symbols`: top-level definitions
- `imports`: imported modules or paths
- `signature`: compact embedding-oriented summary, at most 600 characters

The index also contains `repo_path`, `unit_count`, and `total_loc`.

Skip `.git`, `.venv`, `node_modules`, `__pycache__`, `dist`, `build`, binary
files, files larger than 400 KB, and common lockfiles. Parsing failures must
degrade to empty metadata and never crash indexing.

The CLI contract is:

```text
python -m scotoma.cli index <repo_path> --out index.json
```

It writes pretty JSON and prints unit count, total LOC, and language counts.
Python symbols/imports use `ast`; JS/TS use conservative regular expressions.

## Implementation Principles

- Preserve the difference between raw file coverage and relevance-weighted
  coverage everywhere in the UI and pitch.
- Keep trace ingestion vendor-neutral through a normalized event schema.
- Prefer a deterministic, rehearsable demo over unnecessary live-agent risk.
- Make every score inspectable: show the signals that caused a file to rank.
- Treat LLM adjudication as one signal, not unquestionable ground truth.
- Never imply that low coverage proves a defect or high coverage proves safety.
- Optimize for one excellent vertical slice rather than broad integrations.

## Pitch

> Code coverage tells you what your tests didn't execute. Scotoma tells you
> what your agent didn't investigate before reaching a conclusion.

Short alternative:

> Scotoma measures the blind spots behind AI conclusions.

## Current Status

- Idea and product framing selected.
- Metric and demo contract defined.
- Steps 1–4 complete: territory indexer, bounded instrumented agent,
  Risk-Weighted Coverage, claim adjudication, and conclusion flip test.
- Flask validation: 108 total source units, including 83 Python units; 14,552
  nonblank LOC; imports populated for 80 units.
- Python signatures contain prioritized module docs, compact class/method
  groups, top-level functions, and symbol docs. Flask averages 286.7 characters
  for Python units (233.0 for all languages); critical modules use 600.
- First live trace: `gpt-4o-mini`, 7 tool calls, 7/108 units represented, two
  truncated reads, zero full reads. The confident result also conflated signed
  cookies with encrypted/confidential cookies.
- First metric result: 5.51% RWC versus 6.48% naive coverage; 139 dependency
  edges and 71 structurally reachable units; cached rerun made zero embedding
  API calls. Weights tuned to 0.40 semantic, 0.25 structural, 0.35 lexical to
  reduce an observed signing/signals embedding ambiguity.
- Final adjudication uses `gpt-5.5`: `json/tag.py` ranks first (0.54 final
  risk), `sessions.py` second (0.31), and all remaining candidates at 0.02 or
  less. Cached rerun uses zero API calls.
- Flip comparison returned `changed: YES`: the same reference agent corrected
  “confidential/decrypted” to “signed but readable; integrity/authenticity, not
  confidentiality” after the top evidence was preloaded.
- Transcript adapters are dropped from hackathon scope.
- Step 5 frontend complete: chat-led interactive investigation, dark evidence
  map, claims, adjudicated evidence cliff, evidence-injection flip, repository
  folder preview, artifact loading, and projector present mode. Real artifacts
  are bundled for static GitHub Pages deployment.
- Next action: demo rehearsal/pitch, then zero-API ranker evaluation and negative
  control if time remains.

## Working Decisions and Open Questions

- **Project location:** use the current workspace as the project root unless the
  user requests another location.
- **Python version:** Python 3.13.2 is installed and used by `.venv`.
- **Dependencies:** proposed initial set is `openai`, `numpy`, `jinja2`, `rich`,
  and `tiktoken`; Step 1 itself should not make AI calls.
- **Validation target:** the current Flask checkout contains 83 indexed Python
  units (108 source units across all supported languages).
- **API key:** availability has not yet been verified. It is unnecessary for
  Step 1.
- **Transcript formats:** intentionally deferred until the metric engine works.
