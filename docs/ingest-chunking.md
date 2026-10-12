# Ingest Chunking

`ingest` stores each document as a single vector by default. The default Chroma
embedding model reads only the first ~256 tokens, so most of a long document
never reaches vector search. Heading-aware chunking splits a document into
section-sized pieces at ingest time so each section is embedded and retrieved on
its own.

Chunking is off by default. Turn it on per process:

```bash
OPENCRAB_CHUNKING=1 opencrab ingest ./docs
OPENCRAB_CHUNKING=1 opencrab serve
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENCRAB_CHUNKING` | off | `1`/`true`/`yes`/`on` enables chunking |
| `OPENCRAB_CHUNK_MAX_CHARS` | `1200` | Maximum body characters per chunk (header excluded) |

Both are read from the process environment, not from `.env`.

## Splitting Rules

1. Split at ATX headings `#` to `####`. Lines inside ``` or `~~~` fences are
   never treated as headings; a line such as ```` ```code``` ```` is inline code,
   not a fence. An unclosed fence runs to the end of the document.
   `#####` and deeper stay in the body.
2. A section longer than the limit is split again at blank lines.
   - A pipe table (every row starts with `|`, second row is the separator) is
     split by rows, and every piece repeats the header and separator rows.
     Tables without leading pipes are split like ordinary lines.
   - A single line longer than the limit is cut at the last space before the
     limit (never inside its leading indentation), or at the limit when there
     is no space. Non-whitespace characters are never dropped; a piece that
     is only whitespace (possible with very small limits) is discarded.
3. Consecutive pieces of one section are packed together while they fit.
4. A heading with no body text and with subsections produces no chunk; its
   title appears in the heading path of the subsections. A heading with no
   body and no subsections becomes a chunk whose body is the heading line.
5. Text before the first heading becomes a chunk with an empty heading path.

Kordoc output for HWP/PDF is Markdown, so the same rules apply to parsed files.
Plain text without headings is split by paragraph.

## Stored Records

Each chunk becomes one Chroma record:

- id: `{source_id}#{n}`, with `n` starting at 0
- document text: a header followed by the body

  ```text
  문서: <document title>
  절: <heading 1> > <heading 2>

  <body>
  ```

- metadata: the caller's metadata plus `source_id`, `doc_title`,
  `heading_path` (`" > "`-joined), `chunk_index`, `chunk_count`, and
  `node_id` set to the chunk id. A caller-supplied `node_id` moves to
  `source_node_id`, because the reranker merges hits that share a `node_id`.

The document title is taken from `metadata["title"]`, then the stem of
`metadata["source_path"]`, then the stem of `source_id` when it looks like a
path, else `source_id` itself.

The doc store (`sources.json`) still keeps one record per document.

## Writing and Re-ingest

All chunks of a document are written in one upsert call, then ids that belonged
to the same `source_id` but are no longer produced are deleted. That includes
the whole-document record written before chunking was enabled.

- If the upsert fails, nothing is deleted and the previous chunks remain.
- A document with more chunks than Chroma's maximum batch size (5,461 in
  chromadb 1.5) fails with an error instead of being written in parts.
- If a chunk id is already stored for a different `source_id` (for example a
  document whose id is `doc#0`), nothing is written and an error is returned.
- Re-ingesting text with no content removes the document's previous chunks.
- Ingest assumes one writer at a time. Concurrent ingests of the same document,
  or of a document whose id looks like another's chunk id, can interleave and
  leave a mix of both versions.

The ingest result reports `chunks` and `vector_ids`. The MCP `ontology_ingest`
tool passes on only `stores`, where the Chroma entry reads `ok (<n> chunks)`.

## Not Covered Yet

- BM25 (`query_bm25` and the BM25 leg of `ontology_query`) indexes graph nodes
  only, so chunks are reachable through vector search alone.
- Query results return the full chunk text.
- The embedding model is still Chroma's default English model.
