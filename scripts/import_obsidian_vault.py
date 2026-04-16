from __future__ import annotations

import argparse
import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opencrab.ontology.builder import OntologyBuilder
from opencrab.stores.local_doc_store import LocalDocStore
from opencrab.stores.neo4j_store import Neo4jStore
from opencrab.stores.sql_store import SQLStore

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_가-힣\-/]+)")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


@dataclass(frozen=True)
class NoteRecord:
    path: Path
    rel_path: str
    title: str
    note_doc_id: str
    note_text_id: str
    note_topic_id: str
    text: str
    frontmatter: dict[str, Any]
    tags: list[str]
    wikilinks: list[str]
    folders: list[str]


def sha_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "-", value.lower()).strip("-") or "node"


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw

    frontmatter: dict[str, Any] = {}
    block = match.group(1)
    current_key: str | None = None

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_key:
            frontmatter.setdefault(current_key, [])
            frontmatter[current_key].append(stripped[2:].strip().strip("'\""))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        if not value:
            frontmatter[key] = []
            continue
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
            frontmatter[key] = items
        else:
            frontmatter[key] = value.strip("'\"")

    return frontmatter, raw[match.end():]


def normalize_wikilink(link: str) -> str:
    core = link.split("|", 1)[0].split("#", 1)[0].strip()
    core = core.replace("\\", "/")
    if core.endswith(".md"):
        core = core[:-3]
    return core


def build_note_record(root: Path, path: Path) -> NoteRecord:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = parse_frontmatter(raw)
    rel_path = path.relative_to(root).as_posix()
    title = str(frontmatter.get("title") or path.stem)
    workspace_id = vault_workspace_id(root)

    inline_tags = TAG_RE.findall(body)
    fm_tags = frontmatter.get("tags") or []
    if isinstance(fm_tags, str):
        fm_tags = [fm_tags]
    tags = sorted({tag.strip("#") for tag in [*fm_tags, *inline_tags] if tag})

    wikilinks = [normalize_wikilink(match) for match in WIKILINK_RE.findall(body)]
    folders = rel_path.split("/")[:-1]

    return NoteRecord(
        path=path,
        rel_path=rel_path,
        title=title,
        note_doc_id=sha_id("doc-obsidian", f"{workspace_id}::{rel_path}"),
        note_text_id=sha_id("text-obsidian", f"{workspace_id}::{rel_path}"),
        note_topic_id=sha_id("topic-note", f"{workspace_id}::{rel_path}"),
        text=body.strip(),
        frontmatter=frontmatter,
        tags=tags,
        wikilinks=[link for link in wikilinks if link],
        folders=folders,
    )


def folder_topic_id(workspace_id: str, folder_path: str) -> str:
    return sha_id("topic-folder", f"{workspace_id}::{folder_path}")


def tag_topic_id(workspace_id: str, tag: str) -> str:
    return sha_id("topic-tag", f"{workspace_id}::{tag.lower()}")


def unresolved_link_topic_id(workspace_id: str, link: str) -> str:
    return sha_id("topic-link", f"{workspace_id}::{link.lower()}")


def vault_workspace_id(vault_root: Path) -> str:
    digest = hashlib.sha1(str(vault_root.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"obsidian-{slugify(vault_root.name)}-{digest}"


def note_theme(note: NoteRecord) -> str:
    haystack = " ".join([note.rel_path, note.title, *note.tags]).lower()
    if any(term in haystack for term in ["조경", "landscape", "garden", "tree", "plant", "정원"]):
        return "landscape"
    if any(term in haystack for term in ["alex", "alexai"]):
        return "alex"
    if any(term in haystack for term in ["ai", "agent", "llm", "rag", "ontology", "neo4j", "opencrab"]):
        return "ai"
    return "default"


def topic_theme(name: str) -> str:
    haystack = name.lower()
    if any(term in haystack for term in ["조경", "landscape", "garden", "tree", "plant", "정원"]):
        return "landscape"
    if any(term in haystack for term in ["alex", "alexai"]):
        return "alex"
    if any(term in haystack for term in ["ai", "agent", "llm", "rag", "ontology", "neo4j", "opencrab"]):
        return "ai"
    return "default"


def theme_color(theme: str) -> str:
    palette = {
        "landscape": "#5ea85b",
        "ai": "#e38b2c",
        "alex": "#d97ab5",
        "default": "#7f8c8d",
    }
    return palette.get(theme, palette["default"])


def excerpt(text: str, limit: int = 1200) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def import_vault(vault_root: Path, neo4j_uri: str, neo4j_user: str, neo4j_password: str, neo4j_database: str, local_data_dir: Path) -> dict[str, int]:
    files = sorted(vault_root.rglob("*.md"))
    notes = [build_note_record(vault_root, path) for path in files]
    workspace_id = vault_workspace_id(vault_root)

    note_by_rel = {note.rel_path[:-3] if note.rel_path.endswith(".md") else note.rel_path: note for note in notes}
    note_by_basename: dict[str, list[NoteRecord]] = defaultdict(list)
    for note in notes:
        note_by_basename[note.path.stem].append(note)

    graph = Neo4jStore(neo4j_uri, neo4j_user, neo4j_password, database=neo4j_database)
    docs = LocalDocStore(str(local_data_dir / "docs"))
    sql = SQLStore(f"sqlite:///{local_data_dir / 'opencrab.db'}")
    builder = OntologyBuilder(graph, docs, sql)

    node_count = 0
    edge_count = 0
    edge_props = {
        "source": "obsidian",
        "workspace_id": workspace_id,
        "workspace_label": vault_root.name,
    }

    folder_paths = set()
    tag_names = set()
    unresolved_links = set()

    for note in notes:
        for depth in range(1, len(note.folders) + 1):
            folder_paths.add("/".join(note.folders[:depth]))
        tag_names.update(note.tags)
        for link in note.wikilinks:
            target = note_by_rel.get(link)
            if target is None and len(note_by_basename.get(Path(link).name, [])) != 1:
                unresolved_links.add(link)

    for folder_path in sorted(folder_paths):
        name = folder_path.split("/")[-1]
        builder.add_node(
            space="concept",
            node_type="Topic",
            node_id=folder_topic_id(workspace_id, folder_path),
            properties={
                "name": name,
                "source": "obsidian",
                "workspace_id": workspace_id,
                "workspace_label": vault_root.name,
                "obsidian_path": folder_path,
                "viz_theme": topic_theme(folder_path),
                "viz_color": theme_color(topic_theme(folder_path)),
            },
        )
        node_count += 1
        parent = folder_path.rsplit("/", 1)[0] if "/" in folder_path else None
        if parent:
            builder.add_edge(
                "concept",
                folder_topic_id(workspace_id, folder_path),
                "part_of",
                "concept",
                folder_topic_id(workspace_id, parent),
                properties=edge_props,
            )
            edge_count += 1

    for tag in sorted(tag_names):
        builder.add_node(
            space="concept",
            node_type="Topic",
            node_id=tag_topic_id(workspace_id, tag),
            properties={
                "name": tag,
                "source": "obsidian",
                "workspace_id": workspace_id,
                "workspace_label": vault_root.name,
                "obsidian_kind": "tag",
                "viz_theme": topic_theme(tag),
                "viz_color": theme_color(topic_theme(tag)),
            },
        )
        node_count += 1

    for link in sorted(unresolved_links):
        builder.add_node(
            space="concept",
            node_type="Topic",
            node_id=unresolved_link_topic_id(workspace_id, link),
            properties={
                "name": Path(link).name,
                "source": "obsidian",
                "workspace_id": workspace_id,
                "workspace_label": vault_root.name,
                "obsidian_kind": "wikilink_stub",
                "obsidian_target": link,
                "viz_theme": topic_theme(link),
                "viz_color": theme_color(topic_theme(link)),
            },
        )
        node_count += 1

    for note in notes:
        theme = note_theme(note)
        color = theme_color(theme)
        text_excerpt = excerpt(note.text)
        title = note.title
        mtime = int(note.path.stat().st_mtime)

        builder.add_node(
            space="resource",
            node_type="Document",
            node_id=note.note_doc_id,
            properties={
                "name": title,
                "title": title,
                "source": "obsidian",
                "source_path": note.rel_path,
                "workspace_label": vault_root.name,
                "workspace_id": workspace_id,
                "summary": text_excerpt[:400],
                "obsidian_rel_path": note.rel_path,
                "obsidian_theme": theme,
                "viz_theme": theme,
                "viz_color": color,
            },
        )
        node_count += 1

        builder.add_node(
            space="evidence",
            node_type="TextUnit",
            node_id=note.note_text_id,
            properties={
                "title": title,
                "text": text_excerpt,
                "source": "obsidian",
                "source_path": note.rel_path,
                "workspace_label": vault_root.name,
                "workspace_id": workspace_id,
                "obsidian_rel_path": note.rel_path,
                "char_count": len(note.text),
                "modified_at": mtime,
                "viz_theme": theme,
                "viz_color": color,
            },
        )
        node_count += 1

        builder.add_node(
            space="concept",
            node_type="Topic",
            node_id=note.note_topic_id,
            properties={
                "name": title,
                "source": "obsidian",
                "workspace_label": vault_root.name,
                "workspace_id": workspace_id,
                "obsidian_kind": "note",
                "obsidian_rel_path": note.rel_path,
                "viz_theme": theme,
                "viz_color": color,
            },
        )
        node_count += 1

        docs.upsert_source(
            source_id=str(note.path.resolve()),
            text=note.text,
            metadata={
                "source": "obsidian",
                "workspace_id": workspace_id,
                "workspace_label": vault_root.name,
                "relative_path": note.rel_path,
                "title": title,
                "tags": note.tags,
                "wikilinks": note.wikilinks,
            },
        )

        builder.add_edge(
            "resource",
            note.note_doc_id,
            "contains",
            "evidence",
            note.note_text_id,
            properties={**edge_props, "source_path": note.rel_path},
        )
        edge_count += 1
        builder.add_edge(
            "evidence",
            note.note_text_id,
            "describes",
            "concept",
            note.note_topic_id,
            properties={**edge_props, "source_path": note.rel_path},
        )
        edge_count += 1

        for depth in range(1, len(note.folders) + 1):
            folder_path = "/".join(note.folders[:depth])
            builder.add_edge(
                "evidence",
                note.note_text_id,
                "describes",
                "concept",
                folder_topic_id(workspace_id, folder_path),
                properties={**edge_props, "source_path": note.rel_path},
            )
            edge_count += 1

        for tag in note.tags:
            builder.add_edge(
                "evidence",
                note.note_text_id,
                "mentions",
                "concept",
                tag_topic_id(workspace_id, tag),
                properties={**edge_props, "source_path": note.rel_path},
            )
            edge_count += 1

        for link in note.wikilinks:
            target = note_by_rel.get(link)
            if target is None:
                basename_matches = note_by_basename.get(Path(link).name, [])
                target_topic_id = basename_matches[0].note_topic_id if len(basename_matches) == 1 else unresolved_link_topic_id(workspace_id, link)
            else:
                target_topic_id = target.note_topic_id
            builder.add_edge(
                "concept",
                note.note_topic_id,
                "related_to",
                "concept",
                target_topic_id,
                properties={**edge_props, "source_path": note.rel_path},
            )
            edge_count += 1

    return {
        "notes": len(notes),
        "nodes_written": node_count,
        "edges_written": edge_count,
        "folder_topics": len(folder_paths),
        "tag_topics": len(tag_names),
        "unresolved_link_topics": len(unresolved_links),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an Obsidian vault into the OpenCrab ontology.")
    parser.add_argument("--vault-root", required=True)
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", "opencrab"))
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "opencrab"))
    parser.add_argument("--local-data-dir", default=os.environ.get("LOCAL_DATA_DIR", "./opencrab_data"))
    args = parser.parse_args()

    result = import_vault(
        vault_root=Path(args.vault_root),
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        neo4j_database=args.neo4j_database,
        local_data_dir=Path(args.local_data_dir),
    )
    print(result)


if __name__ == "__main__":
    main()
