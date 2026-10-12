"""
Local multilingual embeddings for Chroma, run with onnxruntime.

Chroma's default embedding model (all-MiniLM-L6-v2) is English-only. Setting
``OPENCRAB_EMBEDDING_MODEL`` to one of :data:`MODELS` embeds documents and
queries with a multilingual model instead. The model runs in-process from
local files; nothing is sent anywhere and nothing is downloaded at runtime.
Fetch the files once with ``scripts/download_embedding_model.py``, which pins
each model to a repository commit and checks every file's sha256.

Only onnxruntime, tokenizers and numpy are needed, which chromadb already
depends on.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings, Space
from chromadb.utils.embedding_functions import register_embedding_function

MODEL_FILE = "model.onnx"
TOKENIZER_FILE = "tokenizer.json"
MANIFEST_FILE = "opencrab-model.json"


@dataclass(frozen=True)
class ModelSpec:
    """How to fetch and run one supported model."""

    repo: str
    revision: str  # pinned commit of the Hugging Face repository
    files: tuple[tuple[str, str], ...]  # (file under onnx/, sha256)
    pooling: Literal["mean", "cls"]
    query_prefix: str
    document_prefix: str
    max_length: int
    dim: int
    batch_size: int


_E5_TOKENIZER = "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626"

MODELS: dict[str, ModelSpec] = {
    "multilingual-e5-small": ModelSpec(
        repo="intfloat/multilingual-e5-small",
        revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
        files=(
            ("model.onnx", "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665"),
            ("tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
        ),
        pooling="mean", query_prefix="query: ", document_prefix="passage: ",
        max_length=512, dim=384, batch_size=16,
    ),
    "multilingual-e5-base": ModelSpec(
        repo="intfloat/multilingual-e5-base",
        revision="d128750597153bb5987e10b1c3493a34e5a4502a",
        files=(
            ("model.onnx", "84a4d426f7e87a6bf5bf195f0bae2c4a7d15f675b23ca96f42fab8326d7a77aa"),
            ("tokenizer.json", _E5_TOKENIZER),
        ),
        pooling="mean", query_prefix="query: ", document_prefix="passage: ",
        max_length=512, dim=768, batch_size=8,
    ),
    "multilingual-e5-large": ModelSpec(
        repo="intfloat/multilingual-e5-large",
        revision="3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3",
        files=(
            ("model.onnx", "bb5a52503a3ef35247f5b5ae6c473aaae60505dd3ffaef56d7b69e2f84683c05"),
            ("model.onnx_data", "0cf1883fee81c63819a44e2ba0efa51d4043d9759685a4ebebbde97e0623d15c"),
            ("tokenizer.json", _E5_TOKENIZER),
        ),
        pooling="mean", query_prefix="query: ", document_prefix="passage: ",
        max_length=512, dim=1024, batch_size=4,
    ),
    "bge-m3": ModelSpec(
        repo="BAAI/bge-m3",
        revision="5617a9f61b028005a4858fdac845db406aefb181",
        files=(
            ("Constant_7_attr__value", "cdf16f72c5d07b36484056e601ed9687f78477e5d85cee85a34f2406b7fb5906"),
            ("model.onnx", "f84251230831afb359ab26d9fd37d5936d4d9bb5d1d5410e66442f630f24435b"),
            ("model.onnx_data", "1eebfb28493f67bba03ce0ef64bfdc7fc5a3bd9d7493f818bb1d78cd798416b4"),
            ("tokenizer.json", "6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790"),
        ),
        pooling="cls", query_prefix="", document_prefix="",
        max_length=1024, dim=1024, batch_size=4,
    ),
}


def embedding_model_from_env() -> str | None:
    """Return the model named by ``OPENCRAB_EMBEDDING_MODEL``, or None for Chroma's default."""
    raw = os.getenv("OPENCRAB_EMBEDDING_MODEL", "").strip()
    if not raw:
        return None
    if raw not in MODELS:
        raise ValueError(f"Unknown OPENCRAB_EMBEDDING_MODEL={raw!r}; choose one of {', '.join(MODELS)}")
    return raw


def resolve_model_dir(model: str) -> Path:
    """Directory holding the model files: ``OPENCRAB_EMBEDDING_MODEL_DIR`` or ~/.cache/opencrab/models/<model>."""
    override = os.getenv("OPENCRAB_EMBEDDING_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "opencrab" / "models" / model


def model_files_present(model: str, model_dir: Path) -> bool:
    return all((model_dir / name).is_file() for name, _ in MODELS[model].files)


def check_model_dir(model: str, model_dir: Path) -> None:
    """Raise unless ``model_dir`` holds a verified download of ``model``.

    The download script writes the manifest only after every file matched its
    pinned sha256, so a manifest naming this model and revision is required.
    """
    hint = f"Run: python scripts/download_embedding_model.py {model}"
    if not model_files_present(model, model_dir):
        raise FileNotFoundError(f"Embedding model files for {model} not found in {model_dir}. {hint}")
    manifest = model_dir / MANIFEST_FILE
    if not manifest.is_file():
        raise FileNotFoundError(f"{model_dir} has no {MANIFEST_FILE}; the files are unverified. {hint}")
    try:
        recorded = json.loads(manifest.read_text())
    except ValueError:
        recorded = None
    if not isinstance(recorded, dict) or recorded.get("model") != model:
        found = recorded.get("model") if isinstance(recorded, dict) else None
        raise ValueError(f"{model_dir} holds {found!r}, not {model!r}. {hint} into another directory")
    if recorded.get("revision") != MODELS[model].revision:
        raise ValueError(f"{model_dir} holds another revision of {model}. {hint}")


@register_embedding_function
class OnnxEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embed text with a local ONNX export of a supported multilingual model."""

    def __init__(
        self,
        model: str,
        model_dir: str | None = None,
        batch_size: int | None = None,
        *,
        session: Any = None,
        tokenizer: Any = None,
    ) -> None:
        if model not in MODELS:
            raise ValueError(f"Unknown embedding model {model!r}; choose one of {', '.join(MODELS)}")
        self._model = model
        self._spec = MODELS[model]
        self._model_dir = Path(model_dir).expanduser() if model_dir else resolve_model_dir(model)
        self._batch_size = max(1, int(batch_size or self._spec.batch_size))
        self._session = session
        self._tokenizer = tokenizer
        self._output_index: int | None = None
        self._load_lock = threading.Lock()

    def __call__(self, input: Documents) -> Embeddings:
        return self._embed(list(input), self._spec.document_prefix)

    def embed_query(self, input: Documents) -> Embeddings:
        return self._embed(list(input), self._spec.query_prefix)

    @staticmethod
    def name() -> str:
        return "opencrab-onnx"

    def default_space(self) -> Space:
        return "cosine"

    def supported_spaces(self) -> list[Space]:
        return ["cosine", "ip", "l2"]

    def get_config(self) -> dict[str, Any]:
        # The model directory is resolved per process (env or default), never
        # persisted, so a stored collection cannot point at another path.
        return {"model": self._model, "batch_size": self._batch_size}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> OnnxEmbeddingFunction:
        return OnnxEmbeddingFunction(model=config["model"], batch_size=config.get("batch_size"))

    # ------------------------------------------------------------------

    def _embed(self, texts: list[str], prefix: str) -> Embeddings:
        if not texts:
            return []
        session, tokenizer = self._load()
        # Batch texts of similar length together to keep padding small.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        vectors: list[np.ndarray | None] = [None] * len(texts)
        for start in range(0, len(order), self._batch_size):
            batch_ids = order[start : start + self._batch_size]
            batch = [prefix + texts[i] for i in batch_ids]
            for i, vec in zip(batch_ids, self._embed_batch(session, tokenizer, batch)):
                vectors[i] = vec
        return [v for v in vectors if v is not None]

    def _embed_batch(self, session: Any, tokenizer: Any, batch: list[str]) -> list[np.ndarray]:
        encodings = tokenizer.encode_batch(batch)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feed = {"input_ids": input_ids, "attention_mask": attention_mask}
        wanted = {i.name for i in session.get_inputs()}
        if "token_type_ids" in wanted:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        outputs = session.run(None, {k: v for k, v in feed.items() if k in wanted})
        output = np.asarray(outputs[self._output_index or 0])
        pooled = output if output.ndim == 2 else self._pool(output, attention_mask)
        if pooled.shape[-1] != self._spec.dim:
            raise ValueError(
                f"{self._model_dir} produced {pooled.shape[-1]}-dim vectors but {self._model} has "
                f"{self._spec.dim}; the directory holds a different model"
            )
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return list((pooled / np.clip(norms, 1e-12, None)).astype(np.float32))

    def _pool(self, hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        if self._spec.pooling == "cls":
            return hidden[:, 0, :]
        mask = attention_mask[:, :, None].astype(hidden.dtype)
        return (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)

    def _load(self) -> tuple[Any, Any]:
        """Load what was not injected, once, even when called from many threads."""
        if self._session is not None and self._tokenizer is not None and self._output_index is not None:
            return self._session, self._tokenizer
        with self._load_lock:
            session, tokenizer = self._session, self._tokenizer
            if session is None or tokenizer is None:
                check_model_dir(self._model, self._model_dir)
            if tokenizer is None:
                tokenizer = self._load_tokenizer()
            if session is None:
                import onnxruntime

                session = onnxruntime.InferenceSession(
                    str(self._model_dir / MODEL_FILE), providers=["CPUExecutionProvider"]
                )
            output_index = self._pick_output(session)
            self._tokenizer, self._session, self._output_index = tokenizer, session, output_index
            return session, tokenizer

    def _load_tokenizer(self) -> Any:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(self._model_dir / TOKENIZER_FILE))
        tokenizer.enable_truncation(max_length=self._spec.max_length)
        tokenizer.enable_padding()
        return tokenizer

    def _pick_output(self, session: Any) -> int:
        """Prefer an export's own pooled output (bge-m3's sentence_embedding) and check its width."""
        outputs = session.get_outputs()
        names = [o.name for o in outputs]
        index = names.index("sentence_embedding") if "sentence_embedding" in names else 0
        width = (getattr(outputs[index], "shape", None) or [None])[-1]
        if isinstance(width, int) and width != self._spec.dim:
            raise ValueError(
                f"{self._model_dir} produces {width}-dim vectors but {self._model} has {self._spec.dim}; "
                "the directory holds a different model"
            )
        return index
