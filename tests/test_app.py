from __future__ import annotations

import json

import app as app_module


class FakeProcessor:
    def ingest_file(self, _path):
        return True, {"num_chunks": 0}


class FakeGraph:
    is_enabled = False

    def build_graph_from_results(self, *_args, **_kwargs):
        return None

    def fetch_graph_snapshot(self):
        return {"nodes": [], "edges": []}


def test_graph_endpoint_disabled():
    flask_app = app_module.create_app(processor=FakeProcessor(), graph=FakeGraph())
    client = flask_app.test_client()

    response = client.get("/graph-data")
    data = response.get_json()

    assert response.status_code == 200
    assert data["disabled"] is True
    assert data["nodes"] == []
    assert data["edges"] == []


def test_term_search_reads_chunks_json(tmp_path, monkeypatch):
    chunks_root = tmp_path / "chunks"
    doc_dir = chunks_root / "doc_alpha"
    doc_dir.mkdir(parents=True)

    chunks = [
        {
            "id": 1,
            "chunk_id": "doc_alpha#1",
            "source_file": "Contract_A.pdf",
            "text": "This contract includes payment milestones in March 2026.",
        }
    ]
    (doc_dir / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")

    monkeypatch.setattr(app_module, "CHUNK_DIR", chunks_root)

    flask_app = app_module.create_app(processor=FakeProcessor(), graph=FakeGraph())
    client = flask_app.test_client()
    with client.session_transaction() as session:
        session["last_run_doc_ids"] = ["doc_alpha"]

    response = client.get("/term-search?q=contract")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["q"] == "contract"
    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["source_file"] == "Contract_A.pdf"


def test_results_routes_redirect_without_state():
    app_module.LAST_RUN_STATE.clear()
    flask_app = app_module.create_app(processor=FakeProcessor(), graph=FakeGraph())
    client = flask_app.test_client()

    assert client.get("/results/analysis").status_code == 302
    assert client.get("/results/graph").status_code == 302


def test_detect_source_kind_for_bot_outputs():
    assert app_module._detect_source_kind("chatgpt_output.txt") == "bot_output"
    assert app_module._detect_source_kind("invoice_summary.pdf") == "document"
