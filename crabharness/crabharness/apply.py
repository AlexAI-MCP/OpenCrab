"""
CrabHarness → OpenCrab promotion apply.

Reads a PromotionPackage JSON file and writes each node and edge into
the OpenCrab ontology stores via OntologyBuilder.

Each operation returns a receipt_id + receipt_ts (Phase 1 feature).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PromotionPackage


def apply_promotion_package(
    package_path: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Apply a PromotionPackage to OpenCrab.

    Parameters
    ----------
    package_path:
        Path to a JSON file containing a serialised PromotionPackage.
    dry_run:
        If True, validate without writing to any store.

    Returns
    -------
    dict with keys:
        package_id, node_receipts, edge_receipts, errors, dry_run
    """
    path = Path(package_path)
    if not path.exists():
        raise FileNotFoundError(f"Promotion package not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    package = PromotionPackage.model_validate(raw)

    # Import OpenCrab components — optional dependency
    try:
        from opencrab.config import Settings
        from opencrab.ontology.builder import OntologyBuilder
        from opencrab.stores.factory import make_doc_store, make_graph_store, make_sql_store
    except ImportError as exc:
        raise ImportError(
            "opencrab package is required for promotion apply. "
            "Install it with: pip install -e ../  (from the crabharness directory)"
        ) from exc

    settings = Settings()

    node_receipts: list[dict[str, Any]] = []
    edge_receipts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if dry_run:
        # Validate grammar + schema without writing
        from opencrab.grammar.validator import validate_node, validate_node_properties
        for node in package.nodes:
            r = validate_node(node.space, node.node_type)
            if not r.valid:
                errors.append({"node_id": node.node_id, "error": r.error})
            else:
                pr = validate_node_properties(node.node_type, node.properties or {})
                if not pr.valid:
                    errors.append({"node_id": node.node_id, "error": pr.error})
                else:
                    node_receipts.append({
                        "node_id": node.node_id,
                        "space": node.space,
                        "node_type": node.node_type,
                        "status": "dry_run_valid",
                    })
        return {
            "package_id": package.package_id,
            "node_receipts": node_receipts,
            "edge_receipts": edge_receipts,
            "errors": errors,
            "dry_run": True,
        }

    # Live write
    graph = make_graph_store(settings)
    docs = make_doc_store(settings)
    sql = make_sql_store(settings)
    builder = OntologyBuilder(neo4j=graph, mongo=docs, sql=sql)

    for node in package.nodes:
        try:
            result = builder.add_node(
                space=node.space,
                node_type=node.node_type,
                node_id=node.node_id,
                properties=node.properties or {},
            )
            node_receipts.append({
                "node_id": node.node_id,
                "space": node.space,
                "node_type": node.node_type,
                "receipt_id": result.get("receipt_id"),
                "receipt_ts": result.get("receipt_ts"),
                "stores": result.get("stores"),
            })
        except Exception as exc:
            errors.append({"node_id": node.node_id, "error": str(exc)})

    for edge in package.edges:
        try:
            result = builder.add_edge(
                from_space=edge.from_space,
                from_id=edge.from_id,
                relation=edge.relation,
                to_space=edge.to_space,
                to_id=edge.to_id,
            )
            edge_receipts.append({
                "from_id": edge.from_id,
                "relation": edge.relation,
                "to_id": edge.to_id,
                "receipt_id": result.get("receipt_id"),
                "receipt_ts": result.get("receipt_ts"),
                "stores": result.get("stores"),
            })
        except Exception as exc:
            errors.append({
                "edge": f"{edge.from_id} -[{edge.relation}]-> {edge.to_id}",
                "error": str(exc),
            })

    return {
        "package_id": package.package_id,
        "mission_id": package.mission_id,
        "run_id": package.run_id,
        "node_receipts": node_receipts,
        "edge_receipts": edge_receipts,
        "errors": errors,
        "dry_run": False,
        "summary": {
            "nodes_written": len(node_receipts),
            "edges_written": len(edge_receipts),
            "errors": len(errors),
        },
    }
