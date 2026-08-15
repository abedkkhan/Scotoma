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
happen locally in the browser. When a Scotoma API URL is configured, the same
dialog submits the selected source files and question to the hosted pipeline,
polls all five stages, and renders the resulting investigation. The OpenAI key
never enters the browser.

## Deploy the live API

[Deploy the Docker service on Render](https://render.com/deploy?repo=https://github.com/abedkkhan/Scotoma)

The included `render.yaml` asks for `OPENAI_API_KEY`, generates a demo access
token, allows the GitHub Pages origin, and starts `scotoma.server:app`. After
deployment:

1. copy the service URL into **Upload repo → Scotoma API URL**;
2. copy `SCOTOMA_ACCESS_TOKEN` into **Demo access token**;
3. choose a repository folder, enter a question, and run the live audit.

You can also run the API locally:

```bash
cp .env.example .env
set -a && source .env && set +a
.venv/bin/uvicorn scotoma.server:app --reload --port 8000
```

The API accepts bounded source-file uploads, runs jobs asynchronously, and
exposes `POST /api/audits`, `GET /api/audits/{id}`, and `GET /api/health`.
