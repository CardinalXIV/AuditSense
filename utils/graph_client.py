from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Set, Tuple

try:
    from neo4j import GraphDatabase
except ModuleNotFoundError:
    GraphDatabase = None

from utils.config import GRAPH_ENABLED, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

logger = logging.getLogger(__name__)


class Neo4jGraphClient:
    """Thread-safe Neo4j client with lazy connection handling."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str | None,
        enabled: bool = True,
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.enabled = enabled
        self._driver = None
        self._lock = threading.Lock()

    @property
    def is_enabled(self) -> bool:
        return bool(self.enabled and self.password and GraphDatabase is not None)

    def _get_driver(self):
        if not self.is_enabled:
            return None

        if self._driver is not None:
            return self._driver

        with self._lock:
            if self._driver is not None:
                return self._driver

            try:
                driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.user, self.password),
                )
                driver.verify_connectivity()
                self._driver = driver
            except Exception:
                logger.exception("Neo4j connectivity check failed.")
                self._driver = None

            return self._driver

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                self._driver.close()
                self._driver = None

    def build_graph_from_results(
        self,
        results: List[Dict[str, Any]],
        dates_table: List[Dict[str, Any]],
        entities_table: List[Dict[str, Any]] | None = None,
    ) -> None:
        if not results or not (dates_table or entities_table):
            return

        driver = self._get_driver()
        if driver is None:
            return

        doc_map: Dict[str, Dict[str, Any]] = {}
        for doc in results:
            original = str(doc.get("original_filename") or "")
            if not original:
                continue
            doc_map[original] = {
                "doc_id": doc.get("doc_id"),
                "num_chunks": doc.get("num_chunks", 0),
                "source_kind": doc.get("source_kind", "document"),
            }

        if not doc_map:
            return

        try:
            with driver.session() as session:
                for original, meta in doc_map.items():
                    session.execute_write(
                        _upsert_document,
                        doc_id=meta["doc_id"],
                        filename=original,
                        num_chunks=meta["num_chunks"],
                        source_kind=meta["source_kind"],
                    )

                for row in dates_table or []:
                    doc_name = str(row.get("Document") or row.get("source_file") or "")
                    if not doc_name:
                        continue

                    try:
                        chunk_index = int(row.get("Chunk") or row.get("chunk_number") or 0)
                    except (TypeError, ValueError):
                        chunk_index = 0

                    parsed_date = row.get("Parsed Date") or row.get("formatted_date")
                    if not parsed_date:
                        continue

                    context = str(row.get("Context") or row.get("context") or "")

                    if doc_name in doc_map:
                        doc_id = doc_map[doc_name]["doc_id"]
                    else:
                        doc_id = doc_name

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

                for row in entities_table or []:
                    doc_name = str(row.get("Document") or row.get("source_file") or "")
                    entity_name = str(row.get("Entity") or row.get("entity_name") or "").strip()
                    if not doc_name or not entity_name:
                        continue

                    try:
                        chunk_index = int(row.get("Chunk") or row.get("chunk_number") or 0)
                    except (TypeError, ValueError):
                        chunk_index = 0

                    entity_label = str(row.get("Label") or row.get("label") or "ENTITY")
                    doc_id = doc_map.get(doc_name, {}).get("doc_id", doc_name)
                    chunk_id = f"{doc_id}#{chunk_index}"

                    session.execute_write(
                        _upsert_entity_mention,
                        chunk_id=chunk_id,
                        entity_name=entity_name,
                        entity_type=entity_label,
                    )
        except Exception:
            logger.exception("Neo4j write failed for graph build.")

    def fetch_graph_snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        edge_keys: Set[Tuple[str, str, str]] = set()

        driver = self._get_driver()
        if driver is None:
            return {"nodes": [], "edges": []}

        try:
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

                    if d:
                        did = str(d.id)
                        if did not in nodes:
                            nodes[did] = {
                                "id": did,
                                "type": "Document",
                                "label": d.get("filename") or "Document",
                                "source_kind": d.get("source_kind") or "document",
                            }

                    if c:
                        cid = str(c.id)
                        if cid not in nodes:
                            idx = c.get("index")
                            doc_label = (d.get("filename") if d else None) or "Doc"
                            label = f"{doc_label} · ch {idx}" if idx is not None else f"{doc_label} · chunk"
                            context = c.get("context") or ""
                            nodes[cid] = {
                                "id": cid,
                                "type": "Chunk",
                                "label": label,
                                "context": context,
                            }

                    if dt:
                        dtid = str(dt.id)
                        if dtid not in nodes:
                            val = dt.get("value")
                            nodes[dtid] = {
                                "id": dtid,
                                "type": "Date",
                                "label": str(val) if val is not None else "Date",
                            }

                    if e:
                        eid = str(e.id)
                        if eid not in nodes:
                            nodes[eid] = {
                                "id": eid,
                                "type": "Entity",
                                "label": e.get("name") or "Entity",
                            }

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
        except Exception:
            logger.exception("Neo4j read failed for graph snapshot.")
            return {"nodes": [], "edges": []}

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
        }


def _upsert_document(
    tx,
    doc_id: str,
    filename: str,
    num_chunks: int,
    source_kind: str = "document",
):
    tx.run(
        """
        MERGE (d:Document {id: $doc_id})
        ON CREATE SET d.filename = $filename,
                      d.num_chunks = $num_chunks,
                      d.source_kind = $source_kind
        ON MATCH SET  d.filename = $filename,
                      d.num_chunks = $num_chunks,
                      d.source_kind = $source_kind
        """,
        doc_id=doc_id,
        filename=filename,
        num_chunks=num_chunks,
        source_kind=source_kind,
    )


def _upsert_chunk_and_date(
    tx,
    doc_id: str,
    filename: str,
    chunk_index: int,
    context: str,
    date_str: str,
):
    tx.run(
        """
        MERGE (d:Document {id: $doc_id})
        ON CREATE SET d.filename = $filename
        """,
        doc_id=doc_id,
        filename=filename,
    )

    chunk_id = f"{doc_id}#{chunk_index}"

    tx.run(
        """
        MATCH (d:Document {id: $doc_id})
        MERGE (c:Chunk {id: $chunk_id})
        ON CREATE SET c.index = $chunk_index,
                      c.context = $context
        ON MATCH SET  c.context = CASE WHEN c.context IS NULL OR c.context = "" THEN $context ELSE c.context END
        MERGE (d)-[:HAS_CHUNK]->(c)
        """,
        doc_id=doc_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        context=context,
    )

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
        MATCH (c:Chunk {id: $chunk_id})
        MERGE (e:Entity {name: $name})
        ON CREATE SET e.type = $type
        MERGE (c)-[:MENTIONS]->(e)
        """,
        chunk_id=chunk_id,
        name=entity_name,
        type=entity_type,
    )


graph_client = Neo4jGraphClient(
    uri=NEO4J_URI,
    user=NEO4J_USER,
    password=NEO4J_PASSWORD,
    enabled=GRAPH_ENABLED,
)


def close_driver() -> None:
    graph_client.close()


def build_graph_from_results(
    results: List[Dict[str, Any]],
    dates_table: List[Dict[str, Any]],
    entities_table: List[Dict[str, Any]] | None = None,
) -> None:
    graph_client.build_graph_from_results(results, dates_table, entities_table)


def fetch_graph_snapshot() -> Dict[str, List[Dict[str, Any]]]:
    return graph_client.fetch_graph_snapshot()
