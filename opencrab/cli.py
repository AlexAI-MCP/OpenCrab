"""
OpenCrab CLI — Click command interface.

Commands:
  init      Create .env from template
  serve     Start the MCP server (stdio)
  status    Check all store connections
  ingest    Ingest files from a path
  extract   LLM-extract nodes/edges from files into the graph
  query     Run a hybrid query
  manifest  Print the MetaOntology grammar
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="opencrab")
def main() -> None:
    """OpenCrab — MetaOntology MCP server. Carcinization is inevitable."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite existing .env file."
)
def init(force: bool) -> None:
    """Create a .env file from .env.example and show startup instructions."""
    here = Path.cwd()
    src = here / ".env.example"
    dst = here / ".env"

    # Search for .env.example up from cwd (handles running from subdirs)
    if not src.exists():
        pkg_dir = Path(__file__).parent.parent
        src = pkg_dir / ".env.example"

    if dst.exists() and not force:
        console.print(
            "[yellow].env already exists. Use --force to overwrite.[/yellow]"
        )
    else:
        if src.exists():
            shutil.copy(src, dst)
            console.print(f"[green]Created {dst}[/green]")
        else:
            _write_default_env(dst)
            console.print(f"[green]Created default {dst}[/green]")

    console.print(
        Panel(
            "[bold]Next steps:[/bold]\n\n"
            "1. Edit [cyan].env[/cyan] with your credentials.\n"
            "2. Start services:\n"
            "   [cyan]docker-compose up -d[/cyan]\n"
            "3. Add to Claude Code MCP config:\n"
            "   [cyan]claude mcp add opencrab -- opencrab serve[/cyan]\n"
            "4. Seed example data:\n"
            "   [cyan]python scripts/seed_ontology.py[/cyan]",
            title="OpenCrab Setup",
            border_style="green",
        )
    )


def _write_default_env(path: Path) -> None:
    content = """\
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=opencrab
MONGODB_URI=mongodb://root:opencrab@localhost:27017
MONGODB_DB=opencrab
POSTGRES_URL=postgresql://opencrab:opencrab@localhost:5432/opencrab
CHROMA_HOST=localhost
CHROMA_PORT=8000
CHROMA_COLLECTION=opencrab_vectors
MCP_SERVER_NAME=opencrab
MCP_SERVER_VERSION=0.1.0
LOG_LEVEL=INFO
"""
    path.write_text(content)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@main.command()
def serve() -> None:
    """Start the OpenCrab MCP server on stdio (for Claude Code integration)."""
    # Suppress all non-error logging to keep stdio clean
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    from opencrab.mcp.server import MCPServer

    server = MCPServer()
    server.run()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@main.command()
def status() -> None:
    """Check connectivity to all configured data stores."""
    from opencrab.config import get_settings
    from opencrab.stores.factory import (
        make_doc_store,
        make_graph_store,
        make_sql_store,
        make_vector_store,
    )

    cfg = get_settings()
    mode_label = f"[bold cyan]{cfg.storage_mode.upper()} MODE[/bold cyan]"
    storage_loc = cfg.local_data_dir if cfg.is_local else "Docker services"
    console.print(f"\n{mode_label} - storage at: {storage_loc}\n")

    graph  = make_graph_store(cfg)
    vector = make_vector_store(cfg)
    docs   = make_doc_store(cfg)
    sql    = make_sql_store(cfg)

    if cfg.is_local:
        store_rows: list[tuple[str, str, Any]] = [
            ("Graph (SQLite)",    cfg.local_data_dir + "/graph.db",    graph),
            ("Vector (ChromaDB)", cfg.local_data_dir + "/chroma",      vector),
            ("Docs (JSON files)", cfg.local_data_dir + "/docs",        docs),
            ("SQL (SQLite)",      cfg.local_data_dir + "/opencrab.db", sql),
        ]
    else:
        store_rows = [
            ("Graph (Neo4j)",     cfg.neo4j_uri,                      graph),
            ("Docs (MongoDB)",    cfg.mongodb_uri.split("@")[-1],     docs),
            ("SQL (PostgreSQL)",  cfg.postgres_url.split("@")[-1],    sql),
            ("Vector (ChromaDB)", cfg.chroma_url,                     vector),
        ]

    table = Table(title="OpenCrab Store Status", show_header=True, header_style="bold cyan")
    table.add_column("Store", style="bold")
    table.add_column("Path / URL")
    table.add_column("Status")

    for name, url, store in store_rows:
        if store.available:
            try:
                ok = store.ping()
                status_text = "[green]OK[/green]" if ok else "[yellow]CONNECTED (ping failed)[/yellow]"
            except Exception:
                status_text = "[yellow]CONNECTED[/yellow]"
        else:
            status_text = "[red]UNAVAILABLE[/red]"
        table.add_row(name, url, status_text)

    console.print(table)


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--recursive", "-r", is_flag=True, default=False)
@click.option("--extension", "-e", default=".txt,.md,.py", show_default=True)
def ingest(path: str, recursive: bool, extension: str) -> None:
    """Ingest files from PATH into the ontology vector store."""
    from opencrab.config import get_settings
    from opencrab.ontology.query import HybridQuery
    from opencrab.stores.factory import make_doc_store, make_graph_store, make_vector_store

    cfg = get_settings()
    chroma = make_vector_store(cfg)
    neo4j = make_graph_store(cfg)
    mongo = make_doc_store(cfg)
    hybrid = HybridQuery(chroma, neo4j)

    extensions = [e.strip() for e in extension.split(",")]
    root = Path(path)
    files = list(root.rglob("*")) if recursive else list(root.iterdir())
    files = [f for f in files if f.is_file() and f.suffix in extensions]

    if not files:
        console.print(f"[yellow]No files with extensions {extensions} found in {path}[/yellow]")
        return

    console.print(f"[cyan]Ingesting {len(files)} file(s)...[/cyan]")

    ok_count = 0
    for file in files:
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
            if not text.strip():
                continue
            source_id = str(file.resolve())
            meta = {"source_path": str(file), "extension": file.suffix}

            hybrid.ingest(text=text, source_id=source_id, metadata=meta)

            if mongo.available:
                mongo.upsert_source(source_id, text, meta)

            ok_count += 1
            console.print(f"  [green]OK[/green] {file.name} ({len(text)} chars)")
        except Exception as exc:
            console.print(f"  [red]FAIL[/red] {file.name}: {exc}")

    console.print(f"\n[bold green]Ingested {ok_count}/{len(files)} files.[/bold green]")


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--recursive", "-r", is_flag=True, default=False)
@click.option("--extension", "-e", default=".md,.txt,.py", show_default=True)
@click.option("--model", default="claude-haiku-4-5-20251001", show_default=True, help="Claude model for extraction.")
@click.option("--dry-run", is_flag=True, default=False, help="Extract but do not write to stores.")
@click.option("--api-key", default=None, envvar="ANTHROPIC_API_KEY", help="Anthropic API key.")
def extract(
    path: str,
    recursive: bool,
    extension: str,
    model: str,
    dry_run: bool,
    api_key: str | None,
) -> None:
    """LLM-extract ontology nodes/edges from files and write to the graph."""
    from opencrab.config import get_settings
    from opencrab.ontology.builder import OntologyBuilder
    from opencrab.ontology.extractor import LLMExtractor
    from opencrab.stores.factory import make_doc_store, make_graph_store, make_sql_store

    if not api_key:
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set. Pass --api-key or set the env var.[/red]")
        raise SystemExit(1)

    cfg = get_settings()
    graph = make_graph_store(cfg)
    doc = make_doc_store(cfg)
    sql = make_sql_store(cfg)
    builder = OntologyBuilder(graph, doc, sql)
    extractor = LLMExtractor(api_key=api_key, model=model)

    extensions = [e.strip() for e in extension.split(",")]
    root = Path(path)
    files = list(root.rglob("*")) if recursive else list(root.iterdir())
    files = [f for f in files if f.is_file() and f.suffix in extensions]

    if not files:
        console.print(f"[yellow]No files with extensions {extensions} found.[/yellow]")
        return

    console.print(f"[cyan]Extracting ontology from {len(files)} file(s)...[/cyan]")

    total_nodes = 0
    total_edges = 0
    total_errors = 0

    for file in files:
        console.print(f"\n[bold]{file.name}[/bold]")
        try:
            result = extractor.extract_from_file(file)
            console.print(f"  nodes={len(result.nodes)} edges={len(result.edges)}", end="")
            if result.errors:
                console.print(f" [yellow]warn={len(result.errors)}[/yellow]")
                total_errors += len(result.errors)
            else:
                console.print()

            if not dry_run:
                for node in result.nodes:
                    try:
                        builder.add_node(
                            space=node.space,
                            node_type=node.node_type,
                            node_id=node.node_id,
                            properties=node.properties,
                        )
                    except Exception as exc:
                        console.print(f"    [red]node {node.node_id}: {exc}[/red]")

                for edge in result.edges:
                    try:
                        builder.add_edge(
                            from_space=edge.from_space,
                            from_id=edge.from_id,
                            relation=edge.relation,
                            to_space=edge.to_space,
                            to_id=edge.to_id,
                            properties=edge.properties,
                        )
                    except Exception as exc:
                        console.print(f"    [yellow]edge {edge.from_id}→{edge.to_id}: {exc}[/yellow]")

            total_nodes += len(result.nodes)
            total_edges += len(result.edges)
        except Exception as exc:
            console.print(f"  [red]FAIL: {exc}[/red]")
            total_errors += 1

    mode_label = "[dim](dry-run)[/dim]" if dry_run else ""
    console.print(
        f"\n[bold green]Done {mode_label}[/bold green] — "
        f"nodes={total_nodes} edges={total_edges} errors={total_errors}"
    )


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


@main.command()
@click.argument("question")
@click.option("--spaces", "-s", default=None, help="Comma-separated space IDs to filter.")
@click.option("--limit", "-n", default=10, show_default=True)
@click.option("--json-output", is_flag=True, default=False, help="Output raw JSON.")
def query(question: str, spaces: str | None, limit: int, json_output: bool) -> None:
    """Run a hybrid query and print results."""
    from opencrab.config import get_settings
    from opencrab.ontology.query import HybridQuery
    from opencrab.stores.factory import make_graph_store, make_vector_store

    cfg = get_settings()
    chroma = make_vector_store(cfg)
    neo4j = make_graph_store(cfg)
    hybrid = HybridQuery(chroma, neo4j)

    space_filter = [s.strip() for s in spaces.split(",")] if spaces else None

    results = hybrid.query(question=question, spaces=space_filter, limit=limit)

    if json_output:
        click.echo(json.dumps([r.to_dict() for r in results], indent=2, default=str))
        return

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    console.print(f"\n[bold]Query:[/bold] {question}")
    console.print(f"[dim]Found {len(results)} result(s)[/dim]\n")

    for i, result in enumerate(results, 1):
        console.print(
            f"[bold cyan]{i}.[/bold cyan] "
            f"[{result.source}] "
            f"node={result.node_id or '?'} "
            f"score={result.score:.3f}"
        )
        if result.text:
            preview = result.text[:200].replace("\n", " ")
            console.print(f"   [dim]{preview}...[/dim]")
        console.print()


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


@main.command()
@click.option("--json-output", is_flag=True, default=False)
def manifest(json_output: bool) -> None:
    """Print the full MetaOntology OS grammar."""
    from opencrab.grammar.validator import describe_grammar

    grammar = describe_grammar()

    if json_output:
        click.echo(json.dumps(grammar, indent=2))
        return

    console.print(
        Panel(
            "[bold magenta]MetaOntology OS Grammar[/bold magenta]",
            subtitle="OpenCrab",
        )
    )

    # Spaces
    table = Table(title="Spaces", show_header=True)
    table.add_column("Space ID", style="cyan bold")
    table.add_column("Node Types", style="green")
    table.add_column("Description")
    for space_id, spec in grammar["spaces"].items():
        table.add_row(
            space_id,
            ", ".join(spec["node_types"]),
            spec["description"],
        )
    console.print(table)

    # Meta-edges
    edge_table = Table(title="Meta-Edges", show_header=True)
    edge_table.add_column("From", style="cyan")
    edge_table.add_column("To", style="green")
    edge_table.add_column("Relations")
    for edge in grammar["meta_edges"]:
        edge_table.add_row(
            edge["from_space"],
            edge["to_space"],
            ", ".join(edge["relations"]),
        )
    console.print(edge_table)

    # Impact categories
    impact_table = Table(title="Impact Categories", show_header=True)
    impact_table.add_column("ID", style="yellow bold")
    impact_table.add_column("Name", style="cyan")
    impact_table.add_column("Question")
    for cat in grammar["impact_categories"]:
        impact_table.add_row(cat["id"], cat["name"], cat["question"])
    console.print(impact_table)

    # ReBAC
    rebac = grammar["rebac"]
    console.print(
        Panel(
            f"[bold]Object types:[/bold] {', '.join(rebac['object_types'])}\n"
            f"[bold]Permissions:[/bold] {', '.join(rebac['permissions'])}",
            title="ReBAC",
        )
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
