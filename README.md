# Scotoma

> Code coverage tells you what your tests did not execute. Scotoma tells you
> what your AI agent did not investigate before reaching a conclusion.

Scotoma indexes a repository, records an agent's file-level examination depth,
calculates Risk-Weighted Coverage, adjudicates likely blind spots against the
agent's claims, and tests whether injecting the missing evidence changes its
answer.

## Live demo

[Open the interactive Scotoma investigation](https://abedkkhan.github.io/Scotoma/)

The included Flask investigation captured a real failure: an agent claimed
Flask session cookies were confidential and decrypted after touching 7 of 108
files and reading none in full. Scotoma identified the two files that overturn
that conclusion, then verified the corrected answer: signed but readable.

## Run locally

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
export OPENAI_API_KEY="..."

.venv/bin/python -m scotoma.cli index ./repo --out index.json
.venv/bin/python -m scotoma.cli ask ./repo "Your question" --out trace.json
.venv/bin/python -m scotoma.cli cover --index index.json --trace trace.json --out coverage.json
.venv/bin/python -m scotoma.cli adjudicate --index index.json --trace trace.json \
  --coverage coverage.json --out adjudication.json
.venv/bin/python -m scotoma.cli flip --adjudication adjudication.json --out flip.json
```

For the complete implementation notes and current evidence, see
[PROGRESS.md](PROGRESS.md).

## Architecture

```text
Repository → territory index → bounded agent trace → weighted coverage
           → candidate retrieval → claim adjudication → conclusion flip test
```

The GitHub Pages frontend is intentionally static: repository-folder previews
happen locally in the browser, and complete investigations are loaded from CLI
artifacts. No source code or API keys are sent through the demo site.
