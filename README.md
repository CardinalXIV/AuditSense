# AuditSense

## Project Structure

```
Auditsense/
│
├── utils/
│   └── config.py
│
├── pipeline/
│   ├── ingestion.py
│   ├── chunking.py
│   ├── extraction.py
│   ├── graph.py
│   ├── reporting.py
│   └── __init__.py
│
├── data/
│   ├── raw/
│   ├── markdown/
│   ├── chunks/
│   ├── extraction/
│   ├── kg/
│   └── (possibly a run_id directory later)
│
└── output/
    └── reports/
```