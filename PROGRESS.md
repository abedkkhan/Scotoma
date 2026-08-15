# Scotoma — Simple Build Progress

This file explains the project in simple language and records what has been
built. Read this first whenever you return to the project.

## The idea

AI coding agents often answer after reading only part of a repository. They may
say, "I found no SQL injection," without telling us that they ignored most of
the code.

Scotoma measures that blind spot. It will show:

- what the agent examined;
- what it did not examine;
- how relevant the unread code was to the question;
- which unread file is most likely to change the agent's answer.

This is similar to code coverage, but for an AI agent's investigation rather
than for executed tests.

## The main metric

Scotoma will use **Risk-Weighted Coverage**:

```text
relevance of examined code / relevance of all code in the repository
```

This is better than counting files. Reading 5 highly relevant files may be
better than reading 50 irrelevant files.

## Where the project is

The project is in:

```text
/Users/abidkarim/Desktop/Build_something_cool
```

This is the workspace supplied to Codex. It is not in `~/Desktop/scotoma`, but
the Python package itself is correctly named `scotoma`.

## Step 1 — complete

Step 1 built the **territory indexer**. It creates a structured map of all
source files that an agent could investigate. It makes no AI or LLM calls.

### Files created

```text
.venv/                 isolated Python 3.13 environment
scotoma/__init__.py    package entry point
scotoma/index.py       repository indexer
scotoma/cli.py         command-line interface
tests/test_index.py    automated tests
requirements.txt       Python dependencies
pytest.ini             prevents tests in target repos from being collected
.gitignore             ignores generated and temporary files
index.json             generated Flask territory index
```

`PROJECT_MEMORY.md` contains the detailed product and engineering plan. This
file is the shorter, easier progress summary.

### What the indexer does

For every eligible source file, it records exactly:

- `path` — location relative to the repository root;
- `language` — language inferred from the extension;
- `size_bytes` — file size;
- `loc` — number of nonblank lines;
- `symbols` — top-level functions and classes;
- `imports` — imported modules or file paths;
- `signature` — a compact summary, no longer than 600 characters.

Python files are analyzed with Python's `ast` parser. JavaScript and TypeScript
imports and declarations are detected with regular expressions. Broken source
files do not crash the indexer.

Python signatures also include methods declared directly inside top-level
classes. Public methods are listed before private and `__dunder__` methods so
large classes use the 600-character budget for the most meaningful terms. The
public `symbols` field still contains only top-level functions and classes, as
specified.

It ignores Git metadata, virtual environments, dependencies, build output,
Python caches, lockfiles, binary files, symlinks, and files larger than 400 KB.

### How to run it

From the project directory:

```bash
.venv/bin/python -m scotoma.cli index <repository> --out index.json
```

Example:

```bash
.venv/bin/python -m scotoma.cli index targets/flask --out index.json
```

### Flask verification result

The Flask repository was cloned into `targets/flask` and indexed successfully:

```text
Source units: 108
Total nonblank LOC: 14,552

Python: 83
HTML:   20
CSS:     2
SQL:     2
Shell:   1
```

The expected range was approximately 70–90 Python files, and Scotoma found 83.
Imports were populated in 80 of the 108 indexed units. Files without imports,
such as HTML or CSS files, correctly have an empty import list.

After the full signature enrichment, the average is 286.7 characters across
Python units and 233.0 across all units. The lower all-unit average is expected
because HTML, CSS, SQL, and Shell files do not contain Python classes or
docstrings. Both `src/flask/app.py` and `src/flask/sessions.py` use the full
600-character budget. Signatures now contain the module docstring, compact
class-and-method groups, top-level functions, and first-line symbol docstrings
in priority order.

### Three real example units

```json
[
  {
    "path": "docs/conf.py",
    "language": "Python",
    "size_bytes": 3386,
    "loc": 84,
    "symbols": ["github_link", "setup"],
    "imports": ["packaging.version", "pallets_sphinx_themes"],
    "signature": "Path: docs/conf.py | Symbols: github_link, setup"
  },
  {
    "path": "examples/celery/make_celery.py",
    "language": "Python",
    "size_bytes": 102,
    "loc": 3,
    "symbols": [],
    "imports": ["task_app"],
    "signature": "Path: examples/celery/make_celery.py"
  },
  {
    "path": "examples/celery/src/task_app/__init__.py",
    "language": "Python",
    "size_bytes": 1024,
    "loc": 31,
    "symbols": ["create_app", "celery_init_app"],
    "imports": ["celery", "flask"],
    "signature": "Path: examples/celery/src/task_app/__init__.py | Symbols: create_app, celery_init_app"
  }
]
```

### Tests

Four automated tests pass. They verify:

- Python and TypeScript symbols and imports;
- skipped directories, binaries, lockfiles, and oversized files;
- graceful handling of invalid Python syntax;
- the 600-character signature limit;
- class methods enrich signatures without changing the top-level symbol
  contract.

Run them with:

```bash
.venv/bin/python -m pytest -q
```

## Step 2 — complete

Step 2 built a small instrumented reference agent. It answers a repository
question with three tools:

- `list_files` records returned file names at depth `0.05`;
- `search` records files containing search hits at depth `0.25`;
- `read_file` records truncated reads at `0.60` and full reads at `1.00`.

If a file is encountered more than once, Scotoma keeps its highest depth. The
agent is hard-limited to 12 tool calls and is not told that its investigation
is being measured. Tool access is restricted to indexed source files inside the
target repository.

Run it with:

```bash
.venv/bin/python -m scotoma.cli ask targets/flask \
  "How does Flask sign and validate session cookies, and could that signing be bypassed?" \
  --out trace.json
```

### First live trace

The first live run used `gpt-4o-mini` and stopped after 7 tool calls. Only 7 of
108 indexed units appeared in the examined map:

```text
Depth 0.60 (truncated read): 2 files
Depth 0.25 (search hit):     5 files
Depth 1.00 (full read):      0 files
```

The two truncated reads were `src/flask/sessions.py` and
`src/flask/sansio/app.py`. Despite this limited evidence, the answer confidently
described signed cookies as providing confidentiality and referred to their
contents as being decrypted. Flask's default client-side session cookies are
signed for integrity/authenticity, not encrypted for confidentiality. This is a
useful real example of the gap Scotoma is designed to measure.

The normalized trace is stored in `trace.json` with the question, repository,
answer, model, ordered tool calls, result summaries, and per-file examination
depths.

There are now six passing automated tests.

## Step 3 — complete

Step 3 built the explainable Risk-Weighted Coverage engine in
`scotoma/rank.py`.

For each indexed unit it calculates:

- semantic similarity from cached `text-embedding-3-small` embeddings;
- structural proximity, up to three dependency-graph hops from a file read at
  depth 0.50 or greater;
- lexical overlap using normalized source-code tokens;
- combined relevance;
- examination depth from the trace;
- blind risk: `relevance × (1 - depth)`.

The tuned relevance formula is:

```text
relevance = 0.40×semantic + 0.25×structural + 0.35×lexical
```

The first requested formula gave semantic similarity 55% weight. It ranked
`signals.py` first because the embedding confused "signals" with "signing".
Semantic remains the largest individual signal, but lexical evidence now has
enough influence to correct obvious semantic ambiguity. Snake-case identifiers
are split into useful tokens, so `test_session_interface` contributes
`test`, `session`, and `interface`.

Run the metric with:

```bash
.venv/bin/python -m scotoma.cli cover \
  --index index.json --trace trace.json --out coverage.json
```

### First coverage result

```text
Risk-Weighted Coverage: 5.51%
Naive file coverage:     7/108 = 6.48%
Dependency graph edges:  139
Structurally reached:     71 units
Embedding API calls:      0 on cached rerun
```

The first uncached run made two batched embedding calls. Its immediate rerun
made zero calls, proven by `embedding_api_calls` in `coverage.json`.

The leading blind spots include `src/flask/testing.py`,
`src/flask/app.py`, `tests/test_session_interface.py`, and
`src/flask/config.py`. `src/flask/signals.py` remains an embedding false
positive near the top; all sub-signals are retained so this limitation is
visible and can be adjudicated in Step 4.

`coverage.json` stores the headline metrics, weights, cache/API information,
dependency-graph diagnostics, and every unit's semantic, structural, lexical,
depth, relevance, and blind-risk values.

There are now ten passing automated tests.

## Step 4 — complete

Step 4 built retrieve-then-rerank claim adjudication and the conclusion flip
test in `scotoma/adjudicate.py`.

The cheap metric now generates 15 candidates using the union of the top 12 by
blind risk and top units by relevance. This matters because a highly relevant
partially read file such as `sessions.py` can have its raw blind risk suppressed
by depth and otherwise fall outside the candidate set.

The adjudicator:

1. extracts 3–6 atomic claims from the original answer;
2. reads the first 3,000 characters of each candidate;
3. judges 15 candidates concurrently;
4. distinguishes contradiction/qualification from mere support;
5. calculates `adjudicated_risk = P(overturn) × (1 - depth)`;
6. caches claims and judgments by model, prompt version, question, path, and
   content hash.

The ordinary reference agent remains on `gpt-4o-mini`. The evidence adjudicator
uses `gpt-5.5`, because smaller models repeatedly failed to distinguish JSON or
base64 serialization from encryption even with an explicit rubric. A cached
adjudication rerun makes zero API calls.

### Final adjudicated ranking

```text
1. src/flask/json/tag.py  P(overturn)=0.72  depth=0.25  final risk=0.54
2. src/flask/sessions.py  P(overturn)=0.78  depth=0.60  final risk=0.31
3+. remaining candidates P(overturn)<=0.02 and effectively irrelevant
```

`json/tag.py` contradicts the claim that valid session data is decrypted: it
describes a compact JSON serializer used for session data. `sessions.py`
describes signed cookies and imports that serializer, contradicting the claim
that signing supplies confidentiality.

### Flip result

The flip preloaded the top three files in full, then asked the same question
again using the same `gpt-4o-mini` reference agent.

```text
Original answer:
  Secret-key signing ensures confidentiality; valid data is decrypted.

Evidence-loaded answer:
  The cookie is signed, not encrypted. Clients can read its serialized JSON.
  Signing provides integrity and authenticity, not confidentiality.

Independent comparison: changed = YES
```

The artifacts are `adjudication.json` and `flip.json`. There are twelve passing
tests.

## Scope decision

The real Codex/Claude transcript adapter has been dropped from the hackathon
scope. A polished, reliable metric and flip demonstration is more valuable than
a second incomplete ingestion path.

## Step 5 — complete

Step 5 built a polished static frontend in `docs/` for GitHub Pages. Instead of
traditional slides, the demonstration unfolds through a chat-style audit:

- the original question and confident agent answer;
- animated audit stages and the 5.51% headline metric;
- a 108-tile evidence map sized by relevance and lit by examination depth;
- red borders around the two claim-contradicting files;
- extracted claims and their contradiction status;
- the adjudicated 0.540 / 0.312 / 0.020 evidence cliff;
- evidence injection and the signed-but-readable corrected answer;
- side-by-side security-property highlighting;
- present mode for projector delivery.

The frontend also accepts a repository folder for browser-local territory
inventory and accepts all five Scotoma JSON artifacts for visualizing another
investigation. GitHub Pages cannot safely execute the Python agent or store an
OpenAI key, so full analysis remains an honest CLI/backend boundary.

The real Flask artifacts are bundled under `docs/data/`; no demo metric is
mocked. A GitHub Actions workflow deploys `docs/` to Pages, and the root README
links to the live experience.

## Step 6 — complete locally

Step 6 added a real hosted execution path instead of limiting the public UI to
the bundled Flask investigation.

`scotoma/server.py` is a FastAPI service with:

- `POST /api/audits` for a repository folder plus question;
- asynchronous background execution of all five Scotoma stages;
- `GET /api/audits/{id}` for stage/progress/result polling;
- `GET /api/health` for deployment checks;
- 1,500-file, 30 MB upload, and 400 KB per-file limits by default;
- path traversal protection and common-root removal;
- a two-job concurrency ceiling;
- strict GitHub Pages CORS configuration;
- optional `SCOTOMA_ACCESS_TOKEN` protection;
- server-only `OPENAI_API_KEY` handling.

The frontend now sends the selected repository only after explicit confirmation,
polls indexing/agent/coverage/adjudication/flip progress, and replaces the demo
with the new repository's real artifacts. A Dockerfile and Render Blueprint are
included. Sixteen tests pass.

The code is deployable, but the service URL requires connecting a hosting
account and adding `OPENAI_API_KEY`; GitHub Pages cannot host Python itself.

## Next step

Deploy the API through the Render Blueprint, configure its URL/token in the
frontend, then rehearse the live and fallback demo paths.

## Offline evaluation

The flip-verified contradictory files provide ground truth without new model
calls. `scotoma evaluate` compares four rankers:

```text
                         Recall@2   MRR    NDCG@5   relevant ranks
Random (1,000 trials)      0.018   0.082    0.034   —
Semantic only              0.500   1.000    0.613   [1, 6]
Three-signal composite     0.000   0.100    0.000   [10, 16]
Claim adjudicated          1.000   1.000    1.000   [1, 2]
```

This evaluation is included as a frontend tab and is generated automatically
for hosted audits. Eighteen tests pass.
