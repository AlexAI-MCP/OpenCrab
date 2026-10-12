# Multilingual Embeddings

Chroma's default embedding model, `all-MiniLM-L6-v2`, is trained on English.
On Korean text its similarity scores carry little meaning, so vector search
mostly fails for Korean questions that do not repeat the document's words.
`OPENCRAB_EMBEDDING_MODEL` switches vector search to a multilingual model that
runs locally with onnxruntime. No text leaves the machine, and no model is
downloaded at runtime.

## Setup

1. Download the model once, from the repository root:

   ```bash
   python scripts/download_embedding_model.py multilingual-e5-small
   ```

   Files go to `OPENCRAB_EMBEDDING_MODEL_DIR`, or by default
   `~/.cache/opencrab/models/<model>`. The script fetches only the files listed
   for the model, from a pinned commit of its Hugging Face repository, and
   rejects any file whose sha256 differs from the recorded one. Files already
   in place are re-checked on every run and only missing or mismatched files
   are fetched. After all files match, it writes `opencrab-model.json`; the
   vector store refuses a model directory without that manifest.

2. Set the model for every process that ingests or queries:

   ```bash
   OPENCRAB_EMBEDDING_MODEL=multilingual-e5-small opencrab ingest ./docs
   OPENCRAB_EMBEDDING_MODEL=multilingual-e5-small opencrab serve
   ```

3. Re-ingest your documents. Each model stores its vectors in its own
   collection, `<CHROMA_COLLECTION>__<model>`, because vectors from different
   models cannot be compared. Until you re-ingest, the new collection is empty,
   so vector search and the chunk keyword index return nothing. Switching back
   to the default model uses the original collection again.

If the model files or the manifest are missing, or the manifest names another
model or revision, creating the vector store fails with a message naming the
download command (the MCP tools return that message; the CLI exits with it).
A model whose output width does not match fails on the first embedding.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENCRAB_EMBEDDING_MODEL` | unset (Chroma default) | One of the models below |
| `OPENCRAB_EMBEDDING_MODEL_DIR` | `~/.cache/opencrab/models/<model>` | Directory with `model.onnx` and `tokenizer.json` |

Both are read from the process environment, not from `.env`.

## Models

| Model | Download | Dimensions | Max tokens | Pooling | Prefixes | Batch |
| --- | --- | --- | --- | --- | --- | --- |
| `multilingual-e5-small` | 0.45 GB | 384 | 512 | mean | `query: ` / `passage: ` | 16 |
| `multilingual-e5-base` | 1.1 GB | 768 | 512 | mean | `query: ` / `passage: ` | 8 |
| `multilingual-e5-large` | 2.1 GB | 1024 | 512 | mean | `query: ` / `passage: ` | 4 |
| `bge-m3` | 2.2 GB | 1024 | 1024 | CLS | none | 4 |

All four are MIT-licensed. Each uses the default fp32 `onnx/model.onnx` export
published in its Hugging Face repository. Text longer than the token limit is
truncated, so combine this with ingest chunking (`OPENCRAB_CHUNKING=1`, see
[ingest-chunking.md](ingest-chunking.md)).

Cost on 4 CPU cores with ~1,200-character Korean chunks: `multilingual-e5-small`
peaked at about 1.8 GB of memory and took about 0.1 s per chunk; `bge-m3` about
1.9 GB and 1.1-1.6 s per chunk (a 220-chunk corpus takes roughly 4-6 minutes to
ingest).
Each process that loads the model holds its own copy in memory. Chroma passes
a whole document's chunks in one call, so a large document blocks that call
until all its chunks are embedded.

Queries are embedded with the query prefix and documents with the passage
prefix, through Chroma's `embed_query` hook.
