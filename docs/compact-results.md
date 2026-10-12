# Compact Query Results

MCP tool results are JSON text that the client model reads in full, so their
size is paid for on every call. `OPENCRAB_COMPACT_RESULTS=1` makes that text
smaller without removing anything the model needs. Re-encoding the 50
`ontology_query` responses recorded in a 12-question Korean evaluation shrank
them from 34,557 to 10,246 characters on average (−70%).

```bash
OPENCRAB_COMPACT_RESULTS=1 opencrab serve
```

The variable is read from the process environment, not from `.env`.

## What Changes

1. **Characters instead of escapes.** Results were serialized with
   `ensure_ascii=True`, so every Korean or CJK character reached the model as a
   six-character `\uXXXX` escape. Compact mode sends the characters themselves
   and emits no separator whitespace. Surrogate code points, which the escapes
   were guarding against, are joined into their character when they form a
   pair and replaced with U+FFFD when they do not, so the text is always valid
   UTF-8.
2. **No repeated chunk metadata (`ontology_query` only).** A result is treated
   as a chunk record from chunked ingest (see
   [ingest-chunking.md](ingest-chunking.md)) when its `node_id` is
   `{source_id}#{chunk_index}`. Its metadata then drops what the result
   already states: `source_id` and `node_id` (repeated in the result's
   `node_id`); `doc_title` and `heading_path` only when the text actually
   opens with that `문서:`/`절:` header; `source_path` only when it equals the
   source id; and `extension`, `parser` and Kordoc parse-quality fields.
   Everything else is kept, including `chunk_index`, `chunk_count`, `space`
   and any metadata the caller attached at ingest. Scores are rounded to four decimals and an empty
   `graph_context` is omitted. The result's own `node_id` is unchanged, so a
   source id that is a file path still appears there.

Graph-node results and every other tool keep their full fields; only the
encoding (point 1) applies to them. Unset, results are encoded exactly as
before.
