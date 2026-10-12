from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from opencrab.stores.onnx_embedding import (
    MANIFEST_FILE,
    MODELS,
    OnnxEmbeddingFunction,
    check_model_dir,
    embedding_model_from_env,
    model_files_present,
    resolve_model_dir,
)

# ---------------------------------------------------------------------------
# Fakes: a tokenizer that encodes each character, a session that returns
# per-token vectors so pooling is easy to check by hand.
# ---------------------------------------------------------------------------


class FakeEncoding:
    def __init__(self, ids: list[int], mask: list[int]) -> None:
        self.ids = ids
        self.attention_mask = mask


class FakeTokenizer:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def encode_batch(self, texts: list[str]) -> list[FakeEncoding]:
        self.seen.extend(texts)
        width = max(len(t) for t in texts)
        return [
            FakeEncoding([ord(c) % 7 + 1 for c in t] + [0] * (width - len(t)), [1] * len(t) + [0] * (width - len(t)))
            for t in texts
        ]


class FakeNode:
    def __init__(self, name: str, shape: list[Any] | None = None) -> None:
        self.name = name
        self.shape = shape


class FakeSession:
    """Vectors start with (id, 2*id, 1) and are zero-padded to ``dim`` columns."""

    def __init__(
        self,
        inputs: tuple[str, ...] = ("input_ids", "attention_mask"),
        pooled: bool = False,
        width: Any = "dim",
        dim: int = 384,
    ) -> None:
        self._inputs = inputs
        self._pooled = pooled
        self._width = width
        self._dim = dim
        self.calls: list[dict[str, Any]] = []

    def get_inputs(self) -> list[FakeNode]:
        return [FakeNode(n) for n in self._inputs]

    def get_outputs(self) -> list[FakeNode]:
        if self._pooled:
            return [FakeNode("token_embeddings"), FakeNode("sentence_embedding", ["batch", self._width])]
        return [FakeNode("last_hidden_state", ["batch", "seq", self._width])]

    def run(self, output_names: Any, feed: dict[str, Any]) -> list[Any]:
        self.calls.append(feed)
        ids = feed["input_ids"].astype(np.float32)
        hidden = np.zeros(ids.shape + (self._dim,), dtype=np.float32)
        hidden[..., 0], hidden[..., 1], hidden[..., 2] = ids, ids * 2, 1.0
        if self._pooled:
            # Like bge-m3: token states first, then a separately pooled sentence vector.
            sentence = np.zeros((ids.shape[0], self._dim), dtype=np.float32)
            sentence[:, :3] = 2.0
            return [np.zeros_like(hidden), sentence]
        return [hidden]


def _ef(model: str = "multilingual-e5-small", **kwargs: Any) -> tuple[OnnxEmbeddingFunction, FakeTokenizer, FakeSession]:
    tokenizer, session = FakeTokenizer(), kwargs.pop("session", FakeSession(dim=MODELS[model].dim))
    ef = OnnxEmbeddingFunction(model=model, model_dir="/unused", tokenizer=tokenizer, session=session, **kwargs)
    return ef, tokenizer, session


def _fake_model_dir(path: Path, model: str, manifest_model: str | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name, _ in MODELS[model].files:
        (path / name).write_bytes(b"x")
    if manifest_model is not None:
        revision = MODELS[manifest_model].revision
        (path / MANIFEST_FILE).write_text(json.dumps({"model": manifest_model, "revision": revision}))
    return path


def _word_tokenizer_file(path: Path) -> Path:
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    vocab = {"[PAD]": 0, "[UNK]": 1, **{f"w{i}": i + 2 for i in range(20)}}
    tok = Tokenizer(WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    tok.save(str(path / "tokenizer.json"))
    return path


# ---------------------------------------------------------------------------
# Model presets and environment
# ---------------------------------------------------------------------------


def test_presets_cover_supported_models() -> None:
    assert set(MODELS) == {"multilingual-e5-small", "multilingual-e5-base", "multilingual-e5-large", "bge-m3"}
    e5, bge = MODELS["multilingual-e5-small"], MODELS["bge-m3"]
    assert (e5.pooling, e5.query_prefix, e5.document_prefix, e5.dim) == ("mean", "query: ", "passage: ", 384)
    assert (bge.pooling, bge.query_prefix, bge.dim, bge.batch_size) == ("cls", "", 1024, 4)
    for spec in MODELS.values():
        assert len(spec.revision) == 40
        names = [name for name, _ in spec.files]
        assert "model.onnx" in names and "tokenizer.json" in names
        assert all(len(sha) == 64 and "/" not in name for name, sha in spec.files)


def test_env_unset_means_default_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAB_EMBEDDING_MODEL", raising=False)

    assert embedding_model_from_env() is None


def test_env_selects_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL", " bge-m3 ")

    assert embedding_model_from_env() == "bge-m3"


def test_unknown_model_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL", "text-embedding-3-large")

    with pytest.raises(ValueError, match="multilingual-e5-small"):
        embedding_model_from_env()


def test_model_dir_default_override_and_tilde(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENCRAB_EMBEDDING_MODEL_DIR", raising=False)
    assert resolve_model_dir("bge-m3") == Path.home() / ".cache" / "opencrab" / "models" / "bge-m3"

    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL_DIR", str(tmp_path))
    assert resolve_model_dir("bge-m3") == tmp_path

    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL_DIR", "~/models/x")
    assert resolve_model_dir("bge-m3") == Path.home() / "models" / "x"


def test_check_model_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="download_embedding_model.py bge-m3"):
        check_model_dir("bge-m3", tmp_path)

    partial = tmp_path / "partial"
    _fake_model_dir(partial, "multilingual-e5-small")
    assert model_files_present("multilingual-e5-small", partial)
    assert not model_files_present("bge-m3", partial)  # model.onnx_data etc. missing

    other = _fake_model_dir(tmp_path / "other", "bge-m3", manifest_model="multilingual-e5-small")
    with pytest.raises(ValueError, match="holds 'multilingual-e5-small'"):
        check_model_dir("bge-m3", other)

    unverified = _fake_model_dir(tmp_path / "unverified", "bge-m3")
    with pytest.raises(FileNotFoundError, match="unverified"):
        check_model_dir("bge-m3", unverified)

    stale = _fake_model_dir(tmp_path / "stale", "bge-m3")
    (stale / MANIFEST_FILE).write_text(json.dumps({"model": "bge-m3", "revision": "0" * 40}))
    with pytest.raises(ValueError, match="another revision"):
        check_model_dir("bge-m3", stale)

    (stale / MANIFEST_FILE).write_text("not json")
    with pytest.raises(ValueError, match="holds None"):
        check_model_dir("bge-m3", stale)

    good = _fake_model_dir(tmp_path / "good", "bge-m3", manifest_model="bge-m3")
    check_model_dir("bge-m3", good)


def test_missing_model_files_raise_a_clear_error(tmp_path: Path) -> None:
    ef = OnnxEmbeddingFunction(model="multilingual-e5-small", model_dir=str(tmp_path))

    with pytest.raises(FileNotFoundError, match="download_embedding_model.py multilingual-e5-small"):
        ef(["안녕"])


# ---------------------------------------------------------------------------
# Embedding behaviour
# ---------------------------------------------------------------------------


def test_documents_and_queries_get_their_prefixes() -> None:
    ef, tokenizer, _ = _ef()

    ef(["문서"])
    ef.embed_query(["질문"])

    assert tokenizer.seen == ["passage: 문서", "query: 질문"]


def test_bge_queries_get_no_prefix() -> None:
    ef, tokenizer, _ = _ef(model="bge-m3", session=FakeSession(pooled=True, dim=1024))

    ef.embed_query(["질문"])

    assert tokenizer.seen == ["질문"]


def test_mean_pooling_ignores_padding_and_normalizes() -> None:
    ef, _, _ = _ef()

    (alone,) = ef(["a"])
    padded, longer = ef(["a", "aaaa bbbb"])

    assert np.allclose(alone, padded)
    assert not np.allclose(padded, longer)
    ids = [ord(c) % 7 + 1 for c in "passage: a"]
    mean = sum(ids) / len(ids)
    expected = np.array([mean, 2 * mean, 1.0])
    assert np.allclose(alone[:3], expected / np.linalg.norm(expected))
    assert not alone[3:].any()


def test_cls_pooling_takes_first_token() -> None:
    ef, _, _ = _ef(model="bge-m3")

    (vec,) = ef(["xyz"])

    first = ord("x") % 7 + 1
    expected = np.array([first, 2 * first, 1], dtype=np.float32)
    assert np.allclose(vec[:3], expected / np.linalg.norm(expected))


def test_named_sentence_embedding_output_is_preferred() -> None:
    ef, _, _ = _ef(model="bge-m3", session=FakeSession(pooled=True, dim=1024))

    (vec,) = ef(["xyz"])

    assert np.allclose(vec[:3], np.full(3, 1 / np.sqrt(3)))
    assert vec.shape == (1024,)


def test_output_width_must_match_the_model() -> None:
    ef, _, _ = _ef(model="bge-m3", session=FakeSession(width=384, dim=384))

    with pytest.raises(ValueError, match="384-dim vectors but bge-m3 has 1024"):
        ef(["xyz"])


def test_actual_width_is_checked_when_the_declared_width_is_symbolic() -> None:
    ef, _, _ = _ef(model="bge-m3", session=FakeSession(width="hidden", dim=384))

    with pytest.raises(ValueError, match="produced 384-dim vectors but bge-m3 has 1024"):
        ef(["xyz"])


def test_token_type_ids_are_fed_when_the_model_wants_them() -> None:
    session = FakeSession(inputs=("input_ids", "attention_mask", "token_type_ids"))  # e5-small: 384
    ef, _, _ = _ef(session=session)

    ef(["가나"])

    assert set(session.calls[0]) == {"input_ids", "attention_mask", "token_type_ids"}
    assert not session.calls[0]["token_type_ids"].any()


def test_batches_follow_length_but_results_keep_input_order() -> None:
    ef, _, session = _ef(batch_size=2)
    texts = ["aaaaaa", "b", "cccc", "dd", "eeeee"]

    vectors = ef(texts)

    assert len(session.calls) == 3
    widths = [call["input_ids"].shape[1] for call in session.calls]
    assert widths == sorted(widths)
    for text, vec in zip(texts, vectors):
        (single,) = ef([text])
        assert np.allclose(vec, single)


def test_empty_input_and_default_batch_size() -> None:
    ef, _, session = _ef(model="bge-m3")

    assert ef.embed_query([]) == []  # Chroma itself never embeds an empty list
    assert session.calls == []
    assert ef.get_config() == {"model": "bge-m3", "batch_size": 4}


def test_config_round_trip_does_not_persist_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ef, _, _ = _ef(batch_size=3)
    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL_DIR", str(tmp_path))

    rebuilt = OnnxEmbeddingFunction.build_from_config(ef.get_config())

    assert ef.get_config() == {"model": "multilingual-e5-small", "batch_size": 3}
    assert rebuilt.get_config() == ef.get_config()
    assert rebuilt._model_dir == tmp_path
    assert OnnxEmbeddingFunction.name() == "opencrab-onnx"
    assert ef.default_space() == "cosine"


def test_real_tokenizer_file_gets_truncation_and_padding(tmp_path: Path) -> None:
    model_dir = _fake_model_dir(tmp_path, "multilingual-e5-small", manifest_model="multilingual-e5-small")
    _word_tokenizer_file(model_dir)
    session = FakeSession()
    ef = OnnxEmbeddingFunction(model="multilingual-e5-small", model_dir=str(model_dir), session=session)

    ef([" ".join(f"w{i % 20}" for i in range(600)), "w1"])

    ids = session.calls[0]["input_ids"]
    assert ids.shape == (2, 512)  # truncated to max_length, shorter one padded to match
    real_tokens = sorted(int(m.sum()) for m in session.calls[0]["attention_mask"])
    assert real_tokens[0] < 10 and real_tokens[1] == 512


def test_concurrent_first_calls_load_the_model_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    import onnxruntime

    model_dir = _word_tokenizer_file(
        _fake_model_dir(tmp_path, "multilingual-e5-small", manifest_model="multilingual-e5-small")
    )
    created: list[str] = []

    def slow_session(path: str, providers: Any = None) -> FakeSession:
        created.append(path)
        time.sleep(0.1)
        return FakeSession()

    monkeypatch.setattr(onnxruntime, "InferenceSession", slow_session)
    ef = OnnxEmbeddingFunction(model="multilingual-e5-small", model_dir=str(model_dir))
    errors: list[BaseException] = []
    start = threading.Barrier(6, timeout=5)

    def worker() -> None:
        try:
            start.wait()
            ef(["w1 w2"])
        except BaseException as exc:  # noqa: BLE001 - surfaced through `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()

    assert errors == []
    assert len(created) == 1


# ---------------------------------------------------------------------------
# Store wiring
# ---------------------------------------------------------------------------


def test_factory_default_path_never_imports_the_onnx_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from opencrab.config import Settings
    from opencrab.stores.factory import make_vector_store

    monkeypatch.delenv("OPENCRAB_EMBEDDING_MODEL", raising=False)
    monkeypatch.setitem(sys.modules, "opencrab.stores.onnx_embedding", None)  # any import would fail
    store = make_vector_store(Settings(LOCAL_DATA_DIR=str(tmp_path), CHROMA_COLLECTION="vectors"))

    assert store.collection_name == "vectors"


def test_factory_uses_model_specific_collection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from opencrab.config import Settings
    from opencrab.stores.factory import make_vector_store

    model_dir = _fake_model_dir(tmp_path / "model", "multilingual-e5-small", manifest_model="multilingual-e5-small")
    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL", "multilingual-e5-small")
    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL_DIR", str(model_dir))
    store = make_vector_store(Settings(LOCAL_DATA_DIR=str(tmp_path), CHROMA_COLLECTION="vectors"))

    assert store.collection_name == "vectors__multilingual-e5-small"


def test_factory_fails_fast_when_model_files_are_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from opencrab.config import Settings
    from opencrab.stores.factory import make_vector_store

    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("OPENCRAB_EMBEDDING_MODEL_DIR", str(tmp_path / "missing"))

    with pytest.raises(FileNotFoundError, match="download_embedding_model.py bge-m3"):
        make_vector_store(Settings(LOCAL_DATA_DIR=str(tmp_path), CHROMA_COLLECTION="vectors"))


# ---------------------------------------------------------------------------
# Download script
# ---------------------------------------------------------------------------


def _download_module() -> Any:
    path = Path(__file__).parent.parent / "scripts" / "download_embedding_model.py"
    spec = importlib.util.spec_from_file_location("download_embedding_model", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_urls_use_the_pinned_revision() -> None:
    dl = _download_module()
    spec = MODELS["bge-m3"]

    assert dl.file_url("bge-m3", "model.onnx") == f"https://huggingface.co/BAAI/bge-m3/resolve/{spec.revision}/onnx/model.onnx"


def test_fetch_keeps_only_files_with_the_expected_sha256(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dl = _download_module()
    body = b"model bytes"
    monkeypatch.setattr(dl.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(body))

    dl.fetch("https://x/model.onnx", tmp_path / "model.onnx", hashlib.sha256(body).hexdigest())
    assert (tmp_path / "model.onnx").read_bytes() == body

    with pytest.raises(ValueError, match="sha256 mismatch"):
        dl.fetch("https://x/tokenizer.json", tmp_path / "tokenizer.json", "0" * 64)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model.onnx"]  # no partial or bad file left


def test_fetch_rejects_unsafe_names(tmp_path: Path) -> None:
    dl = _download_module()

    for name in ("..", ".hidden"):
        with pytest.raises(ValueError, match="unsafe file name"):
            dl.fetch("https://x/y", tmp_path / name, "0" * 64)


def test_download_refuses_a_directory_holding_another_model(tmp_path: Path) -> None:
    dl = _download_module()
    _fake_model_dir(tmp_path, "multilingual-e5-small", manifest_model="multilingual-e5-small")

    assert dl.main(["bge-m3", "--dest", str(tmp_path)]) == 1


def _sha_of_files(model: str, dl: Any, monkeypatch: pytest.MonkeyPatch, bad: set[str]) -> list[str]:
    """Pretend files hash to their pinned sha256 unless named in ``bad``; record fetches."""
    good = dict(MODELS[model].files)
    fetched: list[str] = []
    monkeypatch.setattr(dl, "sha256_of", lambda path: "0" * 64 if path.name in bad else good[path.name])

    def fake_fetch(url: str, target: Path, sha256: str) -> None:
        fetched.append(target.name)
        target.write_bytes(b"fresh")
        bad.discard(target.name)

    monkeypatch.setattr(dl, "fetch", fake_fetch)
    return fetched


def test_ensure_files_checks_existing_files_and_fetches_only_bad_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dl = _download_module()
    _fake_model_dir(tmp_path, "bge-m3")
    fetched = _sha_of_files("bge-m3", dl, monkeypatch, bad={"tokenizer.json"})

    assert dl.ensure_files("bge-m3", tmp_path) == 1
    assert fetched == ["tokenizer.json"]
    check_model_dir("bge-m3", tmp_path)


def test_manifest_does_not_exempt_files_from_checking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dl = _download_module()
    _fake_model_dir(tmp_path, "multilingual-e5-small", manifest_model="multilingual-e5-small")
    fetched = _sha_of_files("multilingual-e5-small", dl, monkeypatch, bad={"model.onnx"})

    assert dl.main(["multilingual-e5-small", "--dest", str(tmp_path)]) == 0
    assert fetched == ["model.onnx"]


def test_missing_file_with_manifest_is_recovered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dl = _download_module()
    _fake_model_dir(tmp_path, "multilingual-e5-small", manifest_model="multilingual-e5-small")
    (tmp_path / "model.onnx").unlink()
    fetched = _sha_of_files("multilingual-e5-small", dl, monkeypatch, bad=set())

    assert dl.main(["multilingual-e5-small", "--dest", str(tmp_path)]) == 0
    assert fetched == ["model.onnx"]


def test_download_failure_reports_and_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client

    dl = _download_module()

    def broken(url: str, timeout: int) -> Any:
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(dl.urllib.request, "urlopen", broken)

    assert dl.main(["multilingual-e5-small", "--dest", str(tmp_path)]) == 1
    assert not any(p.name.endswith(".part") for p in tmp_path.iterdir())


def test_failed_repair_invalidates_the_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dl = _download_module()
    _fake_model_dir(tmp_path, "multilingual-e5-small", manifest_model="multilingual-e5-small")
    good = dict(MODELS["multilingual-e5-small"].files)
    monkeypatch.setattr(dl, "sha256_of", lambda path: "0" * 64 if path.name == "tokenizer.json" else good[path.name])

    def broken_fetch(url: str, target: Path, sha256: str) -> None:
        raise OSError("network down")

    monkeypatch.setattr(dl, "fetch", broken_fetch)

    assert dl.main(["multilingual-e5-small", "--dest", str(tmp_path)]) == 1
    with pytest.raises(FileNotFoundError, match="unverified"):
        check_model_dir("multilingual-e5-small", tmp_path)


def test_manifest_symlink_is_replaced_not_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dl = _download_module()
    _fake_model_dir(tmp_path, "multilingual-e5-small")
    (tmp_path / "model.onnx").write_bytes(b"verified model")
    (tmp_path / MANIFEST_FILE).symlink_to(tmp_path / "model.onnx")
    _sha_of_files("multilingual-e5-small", dl, monkeypatch, bad=set())

    dl.ensure_files("multilingual-e5-small", tmp_path)

    assert (tmp_path / "model.onnx").read_bytes() == b"verified model"
    assert not (tmp_path / MANIFEST_FILE).is_symlink()
    check_model_dir("multilingual-e5-small", tmp_path)


def test_main_holds_a_directory_lock_while_working(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    dl = _download_module()
    seen: list[str] = []

    def probe(model: str, dest: Path) -> int:
        with open(dest / dl.LOCK_FILE, "a") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append("unlocked")
            except BlockingIOError:
                seen.append("locked")
        raise OSError("stop here")

    monkeypatch.setattr(dl, "ensure_files", probe)

    assert dl.main(["multilingual-e5-small", "--dest", str(tmp_path)]) == 1
    assert seen == ["locked"]


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="needs /proc")
def test_fetch_closes_its_temp_file_when_the_connection_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    dl = _download_module()

    def refuse(url: str, timeout: int) -> Any:
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(dl.urllib.request, "urlopen", refuse)
    before = len(os.listdir("/proc/self/fd"))

    for _ in range(5):
        with pytest.raises(urllib.error.URLError):
            dl.fetch("https://x/model.onnx", tmp_path / "model.onnx", "0" * 64)

    assert len(os.listdir("/proc/self/fd")) == before
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Real model (runs only when the model files have been downloaded)
# ---------------------------------------------------------------------------

REAL_MODEL = os.getenv("OPENCRAB_TEST_EMBEDDING_MODEL", "multilingual-e5-small")


@pytest.mark.skipif(
    not model_files_present(REAL_MODEL, resolve_model_dir(REAL_MODEL)), reason="embedding model not downloaded"
)
def test_real_model_ranks_korean_paraphrases_first(tmp_path: Path) -> None:
    from opencrab.stores.chroma_store import ChromaStore

    ef = OnnxEmbeddingFunction(model=REAL_MODEL)
    store = ChromaStore("u", 0, "real", local_mode=True, local_path=str(tmp_path), embedding_function=ef)
    docs = {
        "lodging": "국내 출장 숙박비는 1박 12만 원을 넘을 수 없다.",
        "meeting": "회의실 예약은 사내 포털에서 하루 전까지 한다.",
        "security": "보안 교육은 매년 상반기에 전 직원이 이수한다.",
        "laptop": "퇴사자는 업무용 노트북을 마지막 근무일까지 자산관리팀에 돌려준다.",
        "remote": "재택근무는 주 2회까지 가능하며 팀장에게 전날까지 신청한다.",
    }
    store.upsert_texts(texts=list(docs.values()), metadatas=[{"k": k} for k in docs], ids=list(docs))
    queries = {
        "호텔비 한도가 얼마야?": "lodging",
        "회사 그만둘 때 컴퓨터는 어디에 반납하나": "laptop",
        "집에서 일하는 건 일주일에 몇 번까지?": "remote",
    }

    for question, expected in queries.items():
        assert store.query(question, n_results=5)[0]["id"] == expected, question
