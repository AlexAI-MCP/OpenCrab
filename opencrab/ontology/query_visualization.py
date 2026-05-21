import time
import uuid

def build_layer_payload(question, query_results, graph, max_hops, limit):
    start_time = time.time()
    nodes = {}
    edges = {}  # Changed to dict to store path_rank
    # Seed nodes from query_results
    for result in query_results:
        node_id = result["id"]
        node = dict(result)
        node["highlight"] = True
        node["hop_distance"] = 0
        nodes[node_id] = node
    # Expand neighbors
    for node_id in list(nodes.keys()):
        neighbors = graph.find_neighbors(node_id, direction='both', depth=max_hops, limit=limit)
        for from_id, to_id, relation, path_rank, neighbor_depth in neighbors:
            # Add edge with path_rank
            edge_tuple = (from_id, to_id, relation)
            if edge_tuple not in edges:
                edges[edge_tuple] = path_rank
            # Add neighbor node if not present
            if to_id not in nodes:
                nodes[to_id] = {"id": to_id, "highlight": False, "hop_distance": neighbor_depth}
            if from_id not in nodes:
                nodes[from_id] = {"id": from_id, "highlight": False, "hop_distance": neighbor_depth}
    # Build edge dicts
    edge_list = []
    for (from_id, to_id, relation), path_rank in edges.items():
        edge_list.append({
            "relation": relation,
            "from_id": from_id,
            "to_id": to_id,
            "path_rank": path_rank
        })
    payload = {
        "id": str(uuid.uuid4()),
        "query": question,
        "timestamp": time.time(),
        "source": "cli",
        "nodes": list(nodes.values()),
        "edges": edge_list,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edge_list),
            "max_hops": max_hops,
            "query_time_ms": int((time.time() - start_time) * 1000)
        }
    }
    return payload
