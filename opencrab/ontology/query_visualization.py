"""Query visualization layer builder."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any


def _now_id() -> tuple[str, str]:
    """
    Generate a layer ID and ISO timestamp.

    Returns
    -------
    tuple[str, str]
        (layer_id, iso_timestamp) where layer_id is like "layer-YYYYMMDD-HHMMSS"
    """
    now = datetime.now()
    layer_id = now.strftime("layer-%Y%m%d-%H%M%S")
    iso_timestamp = now.isoformat()
    return layer_id, iso_timestamp


def build_layer_payload(
    question: str,
    query_results: list[dict[str, Any]],
    graph: Any,
    max_hops: int,
    limit: int,
) -> dict[str, Any]:
    """
    Build a visualization layer payload from query results and graph neighbors.

    Parameters
    ----------
    question : str
        The user's query text
    query_results : list[dict[str, Any]]
        Seed nodes from query, each with 'node_id' key
    graph : Any
        Graph store with find_neighbors() method
    max_hops : int
        Maximum depth for neighbor expansion
    limit : int
        Maximum neighbors per seed node

    Returns
    -------
    dict[str, Any]
        Payload with id, query, timestamp (ISO), source, nodes, edges, metadata
    """
    start_time = time.time()
    layer_id, iso_timestamp = _now_id()

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    # Process seed nodes from query_results
    # Results use 'node_id' key, not 'id'
    seed_ids = []
    for result in query_results:
        node_id = result.get("node_id")
        if not node_id:
            continue  # Defensive: skip seeds without id
        seed_ids.append(node_id)

        # Seed nodes get all their fields plus highlight=True, hop_distance=0
        node = {
            "id": node_id,
            "space": result.get("space"),
            "node_type": result.get("node_type"),
            "properties": result.get("properties", {}),
            "score": result.get("score"),
            "highlight": True,
            "hop_distance": 0,
        }
        nodes[node_id] = node

    # Expand neighbors for each seed
    for seed_id in seed_ids:
        neighbors = graph.find_neighbors(
            seed_id, direction="both", depth=max_hops, limit=limit
        )

        # Neighbors are dicts with: properties, labels, relation_type, depth
        for neighbor in neighbors:
            neighbor_props = neighbor.get("properties", {})
            neighbor_id = neighbor_props.get("id")
            if not neighbor_id:
                continue

            # Add neighbor node if not already present
            if neighbor_id not in nodes:
                labels = neighbor.get("labels", [])
                node_type = labels[0] if labels else None
                nodes[neighbor_id] = {
                    "id": neighbor_id,
                    "space": neighbor_props.get("space"),
                    "node_type": node_type,
                    "properties": neighbor_props,
                    "score": None,
                    "highlight": False,
                    "hop_distance": neighbor.get("depth", 1),
                }

            # Build edge
            # For neighbors found via both-directional search, we need to infer edge direction
            # The relation_type tells us the relationship
            relation = neighbor.get("relation_type", "related")

            # Check if this is an outgoing or incoming edge from seed
            # For simplicity, we'll create edges from seed to neighbor for outgoing
            # and from neighbor to seed for incoming based on typical graph patterns
            # Since we're using direction='both', we add edges as found
            
            # Add edge from seed to neighbor (outgoing from seed perspective)
            edge_key = (seed_id, neighbor_id, relation)
            if edge_key not in edges:
                edges[edge_key] = {
                    "from_id": seed_id,
                    "to_id": neighbor_id,
                    "relation": relation,
                    "from_space": nodes[seed_id].get("space"),
                    "to_space": nodes[neighbor_id].get("space"),
                    "path_rank": 1,
                }

    # Build final lists
    node_list = list(nodes.values())
    edge_list = list(edges.values())

    query_time_ms = int((time.time() - start_time) * 1000)

    payload = {
        "id": layer_id,
        "query": question,
        "timestamp": iso_timestamp,
        "source": "cli",
        "nodes": node_list,
        "edges": edge_list,
        "metadata": {
            "total_nodes": len(node_list),
            "total_edges": len(edge_list),
            "max_hops": max_hops,
            "query_time_ms": query_time_ms,
        },
    }

    return payload
