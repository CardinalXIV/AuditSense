# AuditSense

AuditSense is a local-first procurement audit intelligence app:
- deterministic document parsing and chunking
- date extraction and timeline visualization
- entity extraction (org/person/location + address/contact patterns) and keyword shortcuts
- optional Neo4j graph storage + interactive graph search

## What Changed in This Refactor

- enterprise-style Flask app factory (`create_app`) with route-level hardening
- configurable runtime via environment variables (size limits, graph toggle, host/port)
- robust Neo4j client with lazy connectivity checks and safe fallbacks
- chunk metadata persisted to `chunks.json` for reliable term evidence search
- modernized frontend with reusable templates, static assets, responsive layout, and accessibility improvements
- stronger handling for missing spaCy model (graceful fallback)
- split results UX into two pages: `analysis` and `graph workspace`

## Project Layout

```text
AuditSense/
├── app.py
├── requirements.txt
├── static/
│   ├── css/app.css
│   └── js/
│       ├── index.js
│       └── result.js
├── templates/
│   ├── base.html
│   ├── index.html
│   └── result.html
└── utils/
    ├── config.py
    ├── date_extract.py
    ├── file_processor.py
    ├── graph_client.py
    ├── keywords_tfidf.py
    ├── naming.py
    └── ner.py
```

## Quick Start

1) Create and activate a virtual environment.
2) Install dependencies:

```bash
pip install -r requirements.txt
```

3) Create `.env` (or export vars directly). Minimum:

```dotenv
AUDITSENSE_SECRET_KEY=replace-me
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
```

4) Run:

```bash
python app.py
```

App defaults to `http://127.0.0.1:5000`.

## Docker

Build and run the app container:

```bash
docker compose up --build app
```

If port `5000` is already in use, set `AUDITSENSE_PORT`:

```bash
AUDITSENSE_PORT=5050 docker compose up --build app
```

Run with Neo4j enabled:

```bash
GRAPH_ENABLED=true NEO4J_PASSWORD=your-password docker compose --profile graph up --build
```

Run containerized tests:

```bash
docker compose --profile test run --rm app-test
```

## Environment Variables

| Variable | Default | Purpose |
|---|---:|---|
| `AUDITSENSE_SECRET_KEY` | `dev-secret-change-me` | Flask session secret |
| `AUDIT_PIPELINE_DATA_ROOT` | `./data` | Root for raw/chunks/markdown/extraction/kg |
| `AUDIT_PIPELINE_OUTPUT_ROOT` | `./output` | Generated output root |
| `MAX_CONTENT_LENGTH_MB` | `50` | Upload request size cap |
| `MAX_TERM_MATCHES` | `60` | Max `/term-search` matches returned |
| `GRAPH_ENABLED` | `true` | Toggle Neo4j graph integration |
| `NEO4J_URI` | `neo4j://127.0.0.1:7687` | Neo4j endpoint |
| `NEO4J_USER` | `neo4j` | Neo4j user |
| `NEO4J_PASSWORD` | _unset_ | Neo4j password |
| `FLASK_HOST` | `127.0.0.1` | Flask bind host |
| `FLASK_PORT` | `5000` | Flask bind port |
| `FLASK_DEBUG` | `false` | Flask debug mode |

## Operational Notes

- If Neo4j is disabled or credentials are missing, the app still runs; graph endpoints return empty data.
- Term evidence search prefers `chunks.json`, then falls back to scanning chunk markdown files.
- Upload bot output files (naming contains e.g. `bot`, `chatgpt`, `assistant`) to tag them in the graph as bot-origin documents.
- For production deployment, run behind Gunicorn/uWSGI + reverse proxy and set a strong `AUDITSENSE_SECRET_KEY`.
- Docker runtime uses Gunicorn and exposes port `5000`.
