# utils/graph_client.py

from typing import List, Dict, Any, Set, Tuple

from neo4j import GraphDatabase
from utils.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


# Single shared driver
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def close_driver() -> None:
    driver.close()


def build_graph_from_results(
    results: List[Dict[str, Any]],
    dates_table: List[Dict[str, Any]],
    entities_table: List[Dict[str, Any]] | None = None,
) -> None:
    """
    Phase 1/2:
      - Create Document nodes
      - Create Chunk nodes (for chunks that have at least one date)
      - Create Date nodes
      - Create Entity nodes
      - Relationships:
          (Document)-[:HAS_CHUNK]->(Chunk)-[:MENTIONS_DATE]->(Date)
          (Chunk)-[:MENTIONS]->(Entity)
    """

    if not results or not dates_table:
        # Nothing to write – exit early
        return

    # Map original_filename -> doc_id and num_chunks from your results dicts
    doc_map: Dict[str, Dict[str, Any]] = {}
    for doc in results:
        original = doc["original_filename"]
        doc_map[original] = {
            "doc_id": doc["doc_id"],  # base_id from make_base_id
            "num_chunks": doc["num_chunks"],
        }

    with driver.session() as session:
        # 1) Upsert Document nodes
        for original, meta in doc_map.items():
            session.execute_write(
                _upsert_document,
                doc_id=meta["doc_id"],
                filename=original,
                num_chunks=meta["num_chunks"],
            )

        # 2) Upsert Chunk + Date nodes from dates_table rows
        for row in dates_table:
            # These keys come from DateExtractor.create_dates_dataframe
            doc_name = row["Document"]
            chunk_index = int(row["Chunk"])
            parsed_date = row["Parsed Date"]
            context = row.get("Context", "")

            # Resolve doc_id from original filename; fall back to doc_name if unknown
            if doc_name in doc_map:
                doc_id = doc_map[doc_name]["doc_id"]
            else:
                doc_id = doc_name  # fallback; shouldn't usually happen

            # Normalise date to string (DateExtractor already uses YYYY-MM-DD)
            if hasattr(parsed_date, "isoformat"):
                date_str = parsed_date.isoformat()
            else:
                date_str = str(parsed_date)

            session.execute_write(
                _upsert_chunk_and_date,
                doc_id=doc_id,
                filename=doc_name,
                chunk_index=chunk_index,
                context=context,
                date_str=date_str,
            )

        # 3) Upsert Entity nodes and MENTIONS relationships
        if entities_table:
            for row in entities_table:
                doc_name = row["Document"]
                chunk_index = int(row["Chunk"])
                entity_name = row["Entity"]
                entity_label = row.get("Label") or "ENTITY"

                if not entity_name:
                    continue

                # Resolve doc_id from doc_map as before
                if doc_name in doc_map:
                    doc_id = doc_map[doc_name]["doc_id"]
                else:
                    doc_id = doc_name

                chunk_id = f"{doc_id}#{chunk_index}"

                session.execute_write(
                    _upsert_entity_mention,
                    chunk_id=chunk_id,
                    entity_name=entity_name,
                    entity_type=entity_label,
                )


def _upsert_document(tx, doc_id: str, filename: str, num_chunks: int):
    tx.run(
        """
        MERGE (d:Document {id: $doc_id})
        ON CREATE SET d.filename = $filename,
                      d.num_chunks = $num_chunks
        ON MATCH SET  d.filename = $filename,
                      d.num_chunks = $num_chunks
        """,
        doc_id=doc_id,
        filename=filename,
        num_chunks=num_chunks,
    )


def _upsert_chunk_and_date(
    tx,
    doc_id: str,
    filename: str,
    chunk_index: int,
    context: str,
    date_str: str,
):
    # Ensure Document exists (defensive)
    tx.run(
        """
        MERGE (d:Document {id: $doc_id})
        ON CREATE SET d.filename = $filename
        """,
        doc_id=doc_id,
        filename=filename,
    )

    # Chunk id: base_id + "#" + index
    chunk_id = f"{doc_id}#{chunk_index}"

    tx.run(
        """
        MATCH (d:Document {id: $doc_id})
        MERGE (c:Chunk {id: $chunk_id})
        ON CREATE SET c.index = $chunk_index,
                      c.context = $context
        MERGE (d)-[:HAS_CHUNK]->(c)
        """,
        doc_id=doc_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        context=context,
    )

    # Date node + relationship
    tx.run(
        """
        MERGE (dt:Date {value: date($date_str)})
        WITH dt
        MATCH (c:Chunk {id: $chunk_id})
        MERGE (c)-[:MENTIONS_DATE]->(dt)
        """,
        date_str=date_str,
        chunk_id=chunk_id,
    )


def _upsert_entity_mention(
    tx,
    chunk_id: str,
    entity_name: str,
    entity_type: str,
):
    tx.run(
        """
        // Ensure Chunk exists
        MATCH (c:Chunk {id: $chunk_id})

        // Create or reuse Entity
        MERGE (e:Entity {name: $name})
        ON CREATE SET e.type = $type

        // Link them
        MERGE (c)-[:MENTIONS]->(e)
        """,
        chunk_id=chunk_id,
        name=entity_name,
        type=entity_type,
    )


# ----------------------------------------------------------------------
# Graph snapshot for front-end visualization
# ----------------------------------------------------------------------


def fetch_graph_snapshot() -> Dict[str, List[Dict[str, Any]]]:
    """
    Return a simple snapshot of the graph for visualization.

    nodes: [
      {id, type, label, ...}
    ]
    edges: [
      {source, target, type}
    ]
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    edge_keys: Set[Tuple[str, str, str]] = set()

    with driver.session() as session:
        result = session.run(
            """
            MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)
            OPTIONAL MATCH (c)-[:MENTIONS_DATE]->(dt:Date)
            OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
            RETURN d, c, dt, e
            """
        )

        for record in result:
            d = record["d"]
            c = record["c"]
            dt = record["dt"]
            e = record["e"]

            # ---- Document node ----
            if d:
                did = str(d.id)
                if did not in nodes:
                    nodes[did] = {
                        "id": did,
                        "type": "Document",
                        "label": d.get("filename") or "Document",
                    }

            # ---- Chunk node: short label (doc + chunk number) ----
            if c:
                cid = str(c.id)
                if cid not in nodes:
                    idx = c.get("index")
                    doc_label = (d.get("filename") if d else None) or "Doc"

                    # short, deterministic chunk label
                    if idx is not None:
                        label = f"{doc_label} · ch {idx}"
                    else:
                        label = f"{doc_label} · chunk"

                    context = c.get("context") or ""

                    nodes[cid] = {
                        "id": cid,
                        "type": "Chunk",
                        "label": label,
                        # keep full context if you want to use it later in the UI
                        "context": context,
                    }

            # ---- Date node ----
            if dt:
                dtid = str(dt.id)
                if dtid not in nodes:
                    val = dt.get("value")
                    nodes[dtid] = {
                        "id": dtid,
                        "type": "Date",
                        "label": str(val) if val is not None else "Date",
                    }

            # ---- Entity node ----
            if e:
                eid = str(e.id)
                if eid not in nodes:
                    nodes[eid] = {
                        "id": eid,
                        "type": "Entity",
                        "label": e.get("name") or "Entity",
                    }

            # ---- edges (unchanged) ----
            if d and c:
                key = (str(d.id), str(c.id), "HAS_CHUNK")
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append({"source": key[0], "target": key[1], "type": key[2]})

            if c and dt:
                key = (str(c.id), str(dt.id), "MENTIONS_DATE")
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append({"source": key[0], "target": key[1], "type": key[2]})

            if c and e:
                key = (str(c.id), str(e.id), "MENTIONS")
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append({"source": key[0], "target": key[1], "type": key[2]})

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
    }