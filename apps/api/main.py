from __future__ import annotations

import logging
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / "apps" / ".env", override=False)
load_dotenv(REPO_ROOT / ".env", override=False)

from opencrab.config import get_settings
from opencrab.grammar.manifest import SPACES
from opencrab.grammar.validator import describe_grammar, validate_edge, validate_node
from opencrab.ontology.impact import ImpactEngine
from opencrab.ontology.query import HybridQuery
from opencrab.stores.factory import make_doc_store, make_graph_store, make_sql_store, make_vector_store

logger = logging.getLogger("opencrab.api")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

security = HTTPBearer(auto_error=False)
FREE_MAX_VECTORS = 1000
FREE_MAX_SOURCES = 1
QUERY_EVENTS = {"query"}


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to ingest into the ontology vector layer.")
    source_id: str | None = Field(default=None, description="Optional stable source identifier.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional metadata for the ingested source.")


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural language query.")
    spaces: list[str] | None = Field(default=None, description="Optional space filter.")
    limit: int = Field(default=10, ge=1, le=25, description="Maximum result count.")
    graph_depth: int = Field(default=1, ge=1, le=4, description="Neighborhood expansion depth.")


class ImpactRequest(BaseModel):
    node_id: str = Field(..., min_length=1)
    change_type: str = Field(default="update", min_length=1)
    depth: int = Field(default=2, ge=1, le=5)


class NodeRequest(BaseModel):
    space: str = Field(..., min_length=1)
    node_type: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)


class EdgeRequest(BaseModel):
    from_space: str = Field(..., min_length=1)
    from_id: str = Field(..., min_length=1)
    relation: str = Field(..., min_length=1)
    to_space: str = Field(..., min_length=1)
    to_id: str = Field(..., min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tier: str


@dataclass
class ApiContext:
    settings: Any
    graph: Any
    vector: Any
    docs: Any
    sql: Any
    hybrid: HybridQuery
    impact: ImpactEngine


def _tier() -> str:
    tier = os.getenv("OPENCRAB_TIER", "free").strip().lower()
    return tier if tier in {"free", "pro", "api"} else "free"


def _limits_for_tier(tier: str) -> dict[str, int | None]:
    if tier == "free":
        return {"max_vectors": FREE_MAX_VECTORS, "max_sources": FREE_MAX_SOURCES}
    return {"max_vectors": None, "max_sources": None}


def _space_to_default_type(space_id: str) -> str:
    spec = SPACES.get(space_id, {})
    node_types = spec.get("node_types", [])
    return node_types[0] if node_types else space_id.capitalize()


def _safe_count(fn: Any, default: int = 0) -> int:
    try:
        return int(fn())
    except Exception:
        return default


def _docs_available(docs: Any) -> bool:
    return bool(getattr(docs, "available", False))


def _source_owner(docs: Any, source_id: str) -> str | None:
    if not _docs_available(docs):
        return None

    try:
        source = docs.get_source(source_id)
    except Exception:
        return None

    if not source:
        return None
    metadata = source.get("metadata") or {}
    return metadata.get("user_id")


def _log_event(docs: Any, event_type: str, user_id: str, details: dict[str, Any]) -> None:
    if not _docs_available(docs):
        return

    try:
        docs.log_event(event_type, subject_id=user_id, details=details)
        return
    except TypeError:
        pass
    except Exception as exc:
        logger.debug("Audit log write failed for %s: %s", event_type, exc)
        return

    try:
        docs.log_event(event_type, payload=details, actor=user_id)
    except Exception as exc:
        logger.debug("Audit log write failed for %s: %s", event_type, exc)


def _write_node_doc(
    docs: Any,
    *,
    space: str,
    node_type: str,
    node_id: str,
    properties: dict[str, Any],
) -> str | None:
    if not _docs_available(docs):
        return None

    try:
        return docs.upsert_node_doc(space, node_type, node_id, properties)
    except AttributeError:
        docs.upsert_node(space, node_type, node_id, properties)
        return f"{space}::{node_id}"


def _write_source_doc(docs: Any, source_id: str, text: str, metadata: dict[str, Any]) -> str | None:
    if not _docs_available(docs):
        return None

    created = docs.upsert_source(source_id, text, metadata)
    return created or source_id


def _count_user_nodes(docs: Any, user_id: str) -> int:
    if not _docs_available(docs):
        return 0

    if hasattr(docs, "_db"):
        return int(docs._db["nodes"].count_documents({"properties.owner_id": user_id}))

    try:
        rows = docs.list_nodes()
    except Exception:
        return 0

    return sum(1 for row in rows if (row.get("properties") or {}).get("owner_id") == user_id)


def _count_user_sources(docs: Any, user_id: str) -> int:
    if not _docs_available(docs):
        return 0

    if hasattr(docs, "_db"):
        return int(docs._db["sources"].count_documents({"metadata.user_id": user_id}))

    try:
        rows = docs.list_sources()
    except Exception:
        return 0

    return sum(1 for row in rows if (row.get("metadata") or {}).get("user_id") == user_id)


def _count_user_queries(docs: Any, user_id: str) -> int:
    if not _docs_available(docs):
        return 0

    if hasattr(docs, "_db"):
        return int(docs._db["audit_log"].count_documents({"subject_id": user_id, "event_type": {"$in": list(QUERY_EVENTS)}}))

    try:
        rows = docs.get_audit_log(limit=500)
    except TypeError:
        rows = docs.get_audit_log()
    except Exception:
        return 0

    return sum(1 for row in rows if row.get("actor") == user_id and row.get("event_type") in QUERY_EVENTS)


def _count_total_queries(docs: Any) -> int:
    if not _docs_available(docs):
        return 0

    if hasattr(docs, "_db"):
        return int(docs._db["audit_log"].count_documents({"event_type": {"$in": list(QUERY_EVENTS)}}))

    try:
        rows = docs.get_audit_log(limit=1000)
    except TypeError:
        rows = docs.get_audit_log()
    except Exception:
        return 0

    return sum(1 for row in rows if row.get("event_type") in QUERY_EVENTS)


def _recent_activity(docs: Any, user_id: str, limit: int = 8) -> list[dict[str, Any]]:
    if not _docs_available(docs):
        return []

    if hasattr(docs, "_db"):
        cursor = (
            docs._db["audit_log"]
            .find({"subject_id": user_id}, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return [
            {
                "event_type": row.get("event_type"),
                "timestamp": row.get("timestamp"),
                "details": row.get("details") or {},
            }
            for row in cursor
        ]

    try:
        rows = docs.get_audit_log(limit=100)
    except TypeError:
        rows = docs.get_audit_log()
    except Exception:
        return []

    filtered = [row for row in rows if row.get("actor") == user_id][:limit]
    return [
        {
            "event_type": row.get("event_type"),
            "timestamp": row.get("timestamp"),
            "details": row.get("payload") or {},
        }
        for row in filtered
    ]


def _meter_call(ctx: ApiContext, auth: AuthContext, endpoint: str) -> None:
    if auth.tier != "api":
        return

    _log_event(
        ctx.docs,
        "api_meter",
        auth.user_id,
        {"endpoint": endpoint, "tier": auth.tier},
    )


def _build_context() -> ApiContext:
    settings = get_settings()
    graph = make_graph_store(settings)
    vector = make_vector_store(settings)
    docs = make_doc_store(settings)
    sql = make_sql_store(settings)

    try:
        graph.ensure_constraints()
    except Exception as exc:
        logger.debug("Skipping graph constraint bootstrap: %s", exc)

    return ApiContext(
        settings=settings,
        graph=graph,
        vector=vector,
        docs=docs,
        sql=sql,
        hybrid=HybridQuery(vector, graph),
        impact=ImpactEngine(graph, sql),
    )


def _close_context(ctx: ApiContext | None) -> None:
    if ctx is None:
        return

    for store_name in ("graph", "docs", "vector", "sql"):
        store = getattr(ctx, store_name, None)
        close = getattr(store, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                logger.debug("Failed to close %s: %s", store_name, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    app.state.context = _build_context()
    yield
    _close_context(getattr(app.state, "context", None))


app = FastAPI(
    title="OpenCrab SaaS API",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [
    item.strip()
    for item in os.getenv("OPENCRAB_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_context() -> ApiContext:
    return app.state.context


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> AuthContext:
    expected_api_key = os.getenv("OPENCRAB_API_KEY", "").strip()
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OPENCRAB_API_KEY is not configured.",
        )

    if credentials is None or credentials.scheme.lower() != "bearer" or credentials.credentials != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token.",
        )

    return AuthContext(user_id=x_user_id or "anonymous", tier=_tier())


def _enforce_ingest_limits(ctx: ApiContext, auth: AuthContext, source_id: str) -> None:
    if auth.tier != "free":
        return

    source_owner = _source_owner(ctx.docs, source_id)
    if source_owner and source_owner != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Source '{source_id}' belongs to another user.",
        )

    if source_owner:
        return

    current_sources = _count_user_sources(ctx.docs, auth.user_id)
    if current_sources >= FREE_MAX_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Free tier is limited to {FREE_MAX_SOURCES} source.",
        )

    current_vectors = current_sources
    if current_vectors >= FREE_MAX_VECTORS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Free tier is limited to {FREE_MAX_VECTORS} vectors.",
        )


def _resolve_node_types(ctx: ApiContext, from_space: str, from_id: str, to_space: str, to_id: str) -> tuple[str, str]:
    from_type = _space_to_default_type(from_space)
    to_type = _space_to_default_type(to_space)

    if not getattr(ctx.graph, "available", False):
        return from_type, to_type

    try:
        source_rows = ctx.graph.run_cypher(
            "MATCH (n {id: $id}) RETURN labels(n)[0] AS lbl LIMIT 1",
            {"id": from_id},
        )
        if source_rows and source_rows[0].get("lbl"):
            from_type = source_rows[0]["lbl"]
    except Exception:
        pass

    try:
        target_rows = ctx.graph.run_cypher(
            "MATCH (n {id: $id}) RETURN labels(n)[0] AS lbl LIMIT 1",
            {"id": to_id},
        )
        if target_rows and target_rows[0].get("lbl"):
            to_type = target_rows[0]["lbl"]
    except Exception:
        pass

    return from_type, to_type


@app.get("/api/status")
def get_status(ctx: ApiContext = Depends(get_context)) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "opencrab-api",
        "tier": _tier(),
        "storage_mode": ctx.settings.storage_mode,
        "stores": {
            "graph": {"available": bool(getattr(ctx.graph, "available", False)), "healthy": bool(_safe_count(ctx.graph.ping, 0))},
            "vector": {"available": bool(getattr(ctx.vector, "available", False)), "healthy": bool(_safe_count(ctx.vector.ping, 0))},
            "docs": {"available": bool(getattr(ctx.docs, "available", False)), "healthy": bool(_safe_count(ctx.docs.ping, 0))},
            "sql": {"available": bool(getattr(ctx.sql, "available", False)), "healthy": bool(_safe_count(ctx.sql.ping, 0))},
        },
    }


@app.get("/api/manifest")
def get_manifest(auth: AuthContext = Depends(require_auth)) -> dict[str, Any]:
    ctx = get_context()
    _meter_call(ctx, auth, "/api/manifest")
    return describe_grammar()


@app.post("/api/ingest")
def ingest_text(
    payload: IngestRequest,
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    source_id = payload.source_id or f"{auth.user_id}-{uuid4().hex[:12]}"
    _enforce_ingest_limits(ctx, auth, source_id)

    metadata = dict(payload.metadata)
    metadata.setdefault("user_id", auth.user_id)
    metadata.setdefault("source_id", source_id)

    result = ctx.hybrid.ingest(text=payload.text, source_id=source_id, metadata=metadata)

    source_doc_id = _write_source_doc(ctx.docs, source_id, payload.text, metadata)
    if source_doc_id:
        result["stores"]["documents"] = f"ok (id={source_doc_id})"
    elif _docs_available(ctx.docs):
        result["stores"]["documents"] = "ok"
    else:
        result["stores"]["documents"] = "unavailable"

    _log_event(
        ctx.docs,
        "ingest",
        auth.user_id,
        {
            "source_id": source_id,
            "text_length": len(payload.text),
            "tier": auth.tier,
        },
    )
    _meter_call(ctx, auth, "/api/ingest")

    result["tier"] = auth.tier
    result["usage"] = {
        "user_sources": _count_user_sources(ctx.docs, auth.user_id),
        "user_vectors": _count_user_sources(ctx.docs, auth.user_id),
    }
    return result


@app.post("/api/query")
def query_ontology(
    payload: QueryRequest,
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    results = ctx.hybrid.query(
        question=payload.question,
        spaces=payload.spaces,
        limit=payload.limit,
        graph_depth=payload.graph_depth,
    )

    keyword_fallback: list[dict[str, Any]] = []
    if not results:
        keyword_fallback = ctx.hybrid.keyword_search(
            keyword=payload.question,
            spaces=payload.spaces,
            limit=payload.limit,
        )

    response = {
        "question": payload.question,
        "spaces_filter": payload.spaces,
        "total": len(results),
        "results": [result.to_dict() for result in results],
        "keyword_fallback": keyword_fallback,
    }
    _log_event(
        ctx.docs,
        "query",
        auth.user_id,
        {
            "question": payload.question[:240],
            "result_count": len(results),
            "fallback_count": len(keyword_fallback),
        },
    )
    _meter_call(ctx, auth, "/api/query")
    return response


@app.post("/api/impact")
def analyse_impact(
    payload: ImpactRequest,
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    result = ctx.impact.analyse(
        node_id=payload.node_id,
        change_type=payload.change_type,
        depth=payload.depth,
    ).to_dict()
    _log_event(
        ctx.docs,
        "impact",
        auth.user_id,
        {
            "node_id": payload.node_id,
            "change_type": payload.change_type,
        },
    )
    _meter_call(ctx, auth, "/api/impact")
    return result


@app.post("/api/nodes")
def add_node(
    payload: NodeRequest,
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    validation = validate_node(payload.space, payload.node_type)
    validation.raise_if_invalid()

    properties = dict(payload.properties)
    properties.setdefault("owner_id", auth.user_id)

    response: dict[str, Any] = {
        "node_id": payload.node_id,
        "space": payload.space,
        "node_type": payload.node_type,
        "properties": properties,
        "stores": {},
    }

    if getattr(ctx.graph, "available", False):
        try:
            response["node_data"] = ctx.graph.upsert_node(
                node_type=payload.node_type,
                node_id=payload.node_id,
                properties=properties,
                space_id=payload.space,
            )
            response["stores"]["graph"] = "ok"
        except Exception as exc:
            logger.warning("Graph node write failed for %s: %s", payload.node_id, exc)
            response["stores"]["graph"] = f"error: {exc}"
    else:
        response["stores"]["graph"] = "unavailable"

    if _docs_available(ctx.docs):
        try:
            doc_id = _write_node_doc(
                ctx.docs,
                space=payload.space,
                node_type=payload.node_type,
                node_id=payload.node_id,
                properties=properties,
            )
            response["stores"]["documents"] = f"ok (id={doc_id})" if doc_id else "ok"
        except Exception as exc:
            logger.warning("Document node write failed for %s: %s", payload.node_id, exc)
            response["stores"]["documents"] = f"error: {exc}"
    else:
        response["stores"]["documents"] = "unavailable"

    if getattr(ctx.sql, "available", False):
        try:
            ctx.sql.register_node(payload.space, payload.node_type, payload.node_id)
            response["stores"]["sql"] = "ok"
        except Exception as exc:
            logger.warning("SQL node registry failed for %s: %s", payload.node_id, exc)
            response["stores"]["sql"] = f"error: {exc}"
    else:
        response["stores"]["sql"] = "unavailable"

    _log_event(
        ctx.docs,
        "node_upsert",
        auth.user_id,
        {
            "space": payload.space,
            "node_type": payload.node_type,
            "node_id": payload.node_id,
        },
    )
    _meter_call(ctx, auth, "/api/nodes")
    return response


@app.post("/api/edges")
def add_edge(
    payload: EdgeRequest,
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    validation = validate_edge(payload.from_space, payload.to_space, payload.relation)
    validation.raise_if_invalid()

    from_type, to_type = _resolve_node_types(
        ctx,
        payload.from_space,
        payload.from_id,
        payload.to_space,
        payload.to_id,
    )

    response: dict[str, Any] = {
        "from": {"space": payload.from_space, "id": payload.from_id},
        "relation": payload.relation,
        "to": {"space": payload.to_space, "id": payload.to_id},
        "stores": {},
    }

    if getattr(ctx.graph, "available", False):
        try:
            matched = ctx.graph.upsert_edge(
                from_type,
                payload.from_id,
                payload.relation,
                to_type,
                payload.to_id,
                payload.properties,
            )
            response["stores"]["graph"] = "ok" if matched else "no match"
        except Exception as exc:
            logger.warning("Graph edge write failed for %s -> %s: %s", payload.from_id, payload.to_id, exc)
            response["stores"]["graph"] = f"error: {exc}"
    else:
        response["stores"]["graph"] = "unavailable"

    if getattr(ctx.sql, "available", False):
        try:
            ctx.sql.register_edge(
                payload.from_space,
                payload.from_id,
                payload.relation,
                payload.to_space,
                payload.to_id,
            )
            response["stores"]["sql"] = "ok"
        except Exception as exc:
            logger.warning("SQL edge registry failed for %s -> %s: %s", payload.from_id, payload.to_id, exc)
            response["stores"]["sql"] = f"error: {exc}"
    else:
        response["stores"]["sql"] = "unavailable"

    _log_event(
        ctx.docs,
        "edge_upsert",
        auth.user_id,
        {
            "from_space": payload.from_space,
            "from_id": payload.from_id,
            "relation": payload.relation,
            "to_space": payload.to_space,
            "to_id": payload.to_id,
        },
    )
    _meter_call(ctx, auth, "/api/edges")
    return response


@app.get("/api/usage")
def get_usage(
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    _meter_call(ctx, auth, "/api/usage")

    usage = {
        "nodes": _count_user_nodes(ctx.docs, auth.user_id),
        "vectors": _count_user_sources(ctx.docs, auth.user_id),
        "sources": _count_user_sources(ctx.docs, auth.user_id),
        "queries": _count_user_queries(ctx.docs, auth.user_id),
    }
    system = {
        "nodes": _safe_count(ctx.graph.count_nodes),
        "vectors": _safe_count(ctx.vector.count),
        "queries": _count_total_queries(ctx.docs),
    }
    return {
        "user_id": auth.user_id,
        "tier": auth.tier,
        "limits": _limits_for_tier(auth.tier),
        "usage": usage,
        "system": system,
        "recent_activity": _recent_activity(ctx.docs, auth.user_id),
    }


@app.get("/api/nodes")
def list_nodes(
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    """Return all nodes for graph visualization."""
    try:
        raw = ctx.graph.run_query(
            "MATCH (n) OPTIONAL MATCH (n)-[r]-() "
            "RETURN n.id AS id, n.space AS space, n.node_type AS node_type, "
            "properties(n) AS props, count(r) AS degree "
            "LIMIT 500"
        )
        nodes = []
        for row in (raw or []):
            nid = row.get("id")
            if not nid:
                continue
            props = {k: v for k, v in (row.get("props") or {}).items()
                     if k not in ("id", "space", "node_type")}
            nodes.append({
                "id": nid,
                "space": row.get("space", "concept"),
                "node_type": row.get("node_type", "Node"),
                "properties": props,
                "degree": row.get("degree", 0),
            })
        return {"nodes": nodes, "total": len(nodes)}
    except Exception as exc:
        logger.exception("list_nodes failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/edges")
def list_edges(
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> dict[str, Any]:
    """Return all edges for graph visualization."""
    try:
        raw = ctx.graph.run_query(
            "MATCH (a)-[r]->(b) "
            "RETURN a.id AS from_id, b.id AS to_id, type(r) AS relation, "
            "a.space AS from_space, b.space AS to_space "
            "LIMIT 2000"
        )
        edges = []
        for row in (raw or []):
            if not row.get("from_id") or not row.get("to_id"):
                continue
            edges.append({
                "from_id": row["from_id"],
                "to_id": row["to_id"],
                "relation": row.get("relation", "relates_to"),
                "from_space": row.get("from_space", "concept"),
                "to_space": row.get("to_space", "concept"),
            })
        return {"edges": edges, "total": len(edges)}
    except Exception as exc:
        logger.exception("list_edges failed")
        raise HTTPException(status_code=500, detail=str(exc))


## ─── Remote MCP Server (Streamable HTTP, 2025-03-26) ────────────────────────

MCP_TOOLS = [
    {
        "name": "ontology_query",
        "description": "Hybrid vector + graph search across the ontology",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "spaces": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["question"],
        },
    },
    {
        "name": "ontology_ingest",
        "description": "Ingest text into the ontology vector and graph stores",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source_id": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "ontology_manifest",
        "description": "Return the full MetaOntology grammar: spaces, relations, impact categories",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ontology_add_node",
        "description": "Add or update a node in the ontology",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "node_type": {"type": "string"},
                "node_id": {"type": "string"},
                "properties": {"type": "object"},
            },
            "required": ["space", "node_type", "node_id"],
        },
    },
    {
        "name": "ontology_add_edge",
        "description": "Add a directed edge between two nodes (grammar-validated)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_space": {"type": "string"},
                "from_id": {"type": "string"},
                "relation": {"type": "string"},
                "to_space": {"type": "string"},
                "to_id": {"type": "string"},
            },
            "required": ["from_space", "from_id", "relation", "to_space", "to_id"],
        },
    },
    {
        "name": "ontology_impact",
        "description": "Impact analysis: which I1-I7 categories are triggered by a node change",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "change_type": {"type": "string", "default": "update"},
                "depth": {"type": "integer", "default": 2},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "ontology_lever_simulate",
        "description": "Predict downstream outcome changes from a lever movement",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lever_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["raises", "lowers", "stabilizes", "optimizes"]},
                "magnitude": {"type": "number", "default": 0.5},
            },
            "required": ["lever_id", "direction"],
        },
    },
]


def _mcp_text(data: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}]}


async def _mcp_dispatch(tool_name: str, args: dict[str, Any], auth: AuthContext, ctx: ApiContext) -> Any:
    if tool_name == "ontology_query":
        result = ctx.hybrid.query(
            question=args["question"],
            spaces=args.get("spaces"),
            limit=args.get("limit", 10),
            graph_depth=args.get("graph_depth", 1),
        )
        return result if isinstance(result, dict) else {"results": result}

    if tool_name == "ontology_ingest":
        source_id = args.get("source_id") or f"mcp-{uuid4().hex[:8]}"
        meta = dict(args.get("metadata") or {})
        meta.setdefault("user_id", auth.user_id)
        vec_id = ctx.vector.upsert(source_id, args["text"], meta)
        _write_source_doc(ctx.docs, source_id, args["text"], meta)
        return {"source_id": source_id, "vector_id": vec_id, "status": "ok"}

    if tool_name == "ontology_manifest":
        return describe_grammar()

    if tool_name == "ontology_add_node":
        space = args["space"]
        node_type = args.get("node_type", _space_to_default_type(space))
        node_id = args["node_id"]
        props = dict(args.get("properties") or {})
        err = validate_node(space, node_type)
        if err:
            return {"error": err}
        props.update({"id": node_id, "space": space, "node_type": node_type})
        ctx.graph.upsert_node(space, node_type, node_id, props)
        return {"node_id": node_id, "space": space, "node_type": node_type, "status": "ok"}

    if tool_name == "ontology_add_edge":
        err = validate_edge(args["from_space"], args["relation"], args["to_space"])
        if err:
            return {"error": err}
        ctx.graph.upsert_edge(
            args["from_space"], args["from_id"],
            args["relation"],
            args["to_space"], args["to_id"],
            args.get("properties") or {},
        )
        return {"status": "ok", "relation": args["relation"]}

    if tool_name == "ontology_impact":
        result = ctx.impact.analyze(args["node_id"], args.get("change_type", "update"), args.get("depth", 2))
        return result if isinstance(result, dict) else {"impact": result}

    if tool_name == "ontology_lever_simulate":
        result = ctx.impact.simulate_lever(args["lever_id"], args["direction"], args.get("magnitude", 0.5))
        return result if isinstance(result, dict) else {"simulation": result}

    return {"error": f"Unknown tool: {tool_name}"}


@app.get("/mcp")
async def mcp_info() -> dict[str, Any]:
    return {
        "name": "opencrab",
        "version": "0.1.0",
        "protocol": "2025-03-26",
        "endpoint": "/mcp",
        "tools": len(MCP_TOOLS),
    }


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    auth: AuthContext = Depends(require_auth),
    ctx: ApiContext = Depends(get_context),
) -> Any:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params") or {}

    def ok(result: Any) -> JSONResponse:
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    def err(code: int, message: str) -> JSONResponse:
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}})

    if method == "initialize":
        return ok({
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "opencrab", "version": "0.1.0"},
        })

    if method in ("notifications/initialized", "ping"):
        return ok({})

    if method == "tools/list":
        return ok({"tools": MCP_TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            result = await _mcp_dispatch(tool_name, args, auth, ctx)
            return ok(_mcp_text(result))
        except Exception as exc:
            logger.exception("MCP tools/call failed: %s", tool_name)
            return err(-32603, str(exc))

    return err(-32601, f"Method not found: {method}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        reload=False,
    )
