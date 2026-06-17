"""
로컬 GGUF 임베딩 EF (ChromaDB EmbeddingFunction 프로토콜) — 폴백용

변경 이유:
  - 원격 OpenAI 호환 서버(primary) 다운/미응답 시에도 검색이 완전히 불가하지
    않도록, 로컬 CPU에서 로컬 GGUF 를 폴백으로 운용.

기본 모델(자동 다운로드):
  - KURE-v1-Q4_K_M (mykor/KURE-v1-gguf, 438MB)
  - Q4_K_M 선택: Q8_0(600MB, ~0.7s) 대비 크기·속도 개선, 품질 손실 ~2%.
  - 다른 모델을 쓰려면 LOCAL_GGUF_PATH 환경변수로 직접 경로 지정.

대안:
  - 더 빠른 소형 모델(e5-small 등): 384d라 EMBED_COLLECTION 과 차원 불일치.
    같은 컬렉션을 재사용하려면 primary 와 동일 모델·차원 필요.
  - CPU 속도는 환경에 따라 다름(예: 4코어 ARM에서 Q4_K_M ~0.45s/건).
    폴백은 primary 장애 시에만 발동되므로 허용.

롤백:
  - EMBEDDING_BACKEND=local 으로 기존 minilm 컬렉션 즉시 복귀.
"""

import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

_EMBEDDING_FUNCTION_NAME = "kure_v1"
# OpenAIEmbeddingFunction.name() 과 동일 문자열 유지.
# ChromaDB 는 컬렉션 메타데이터에 EF name 을 저장하므로, 원격 서버 ↔ 로컬
# 전환 시 같은 name 을 반환해야 같은 컬렉션을 재사용할 수 있다.


class LlamaCppEmbeddingFunction:
    """llama-cpp-python 으로 로컬 KURE-v1 GGUF 를 실행하는 EF.

    Parameters
    ----------
    gguf_path : str
        KURE-v1 GGUF 파일 경로.
        예: "~/.cache/opencrab/models/KURE-v1-Q4_K_M.gguf"
    dim : int
        임베딩 차원. KURE = 1024. primary(원격 서버) 측과 동일해야 함.
    n_threads : int
        CPU 스레드 수. 기본 4.
        코어 수에 맞춰 조정.
    n_ctx : int
        최대 컨텍스트 길이. 512 는 localcrab 청크 크기 대비 충분.
        KURE 원본 max 8192 지만 폴백 검색은 짧은 쿼리가 대부분이라 절약.
    """

    def __init__(
        self,
        gguf_path: str,
        dim: int = 1024,
        n_threads: int = 4,
        n_ctx: int = 512,
    ) -> None:
        self._gguf_path = gguf_path
        self._dim = dim
        self._n_threads = n_threads
        self._n_ctx = n_ctx
        self._llm: Any = None  # lazy load — 폴백 최초 호출 시 로드

    # ------------------------------------------------------------------
    # ChromaDB EmbeddingFunction 프로토콜
    # ------------------------------------------------------------------

    def __call__(self, input: list[str]) -> list[list[float]]:
        """텍스트 리스트 → L2 정규화된 임베딩 리스트."""
        if not input:
            return []
        llm = self._get_llm()
        result = []
        for text in input:
            # create_embedding 은 단건씩 호출 (llama-cpp 내부 배치 없음).
            # KURE 는 쿼리/패시지 프리픽스 불필요 (bge-m3 계열, 대칭 임베딩).
            resp = llm.create_embedding(text)
            vec = resp["data"][0]["embedding"]
            result.append(_l2_normalize(vec))
        return result

    def name(self) -> str:
        """OpenAIEmbeddingFunction 과 동일한 고정 이름 반환."""
        return _EMBEDDING_FUNCTION_NAME

    def embed_query(self, input: list[str]) -> list[list[float]]:
        """ChromaDB 1.5+ 가 query 경로에서 호출하는 메서드.
        KURE 는 쿼리/패시지 임베딩이 대칭이므로 __call__ 과 동일 처리."""
        return self.__call__(input)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _get_llm(self) -> Any:
        """최초 폴백 호출 시 모델 로드(lazy). 이후 캐시.

        GGUF 파일이 없으면 huggingface_hub 로 자동 다운로드를 시도한다.
        다운로드 실패 시 안내 메시지와 함께 RuntimeError 를 발생시킨다.
        """
        if self._llm is None:
            # ── GGUF 파일 존재 확인 / 자동 다운로드 ──────────────────────
            if not self._gguf_path or not os.path.exists(self._gguf_path):
                self._gguf_path = _ensure_local_gguf(self._gguf_path)

            try:
                from llama_cpp import Llama  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "llama-cpp-python 이 설치되지 않았습니다. "
                    "pip install llama-cpp-python 으로 설치하세요."
                ) from exc
            logger.info("로컬 GGUF 로드 중: %s", self._gguf_path)
            self._llm = Llama(
                model_path=self._gguf_path,
                embedding=True,
                n_ctx=self._n_ctx,
                n_threads=self._n_threads,
                verbose=False,
            )
            logger.info("로컬 GGUF 로드 완료 (dim=%d)", self._dim)
        return self._llm


def _l2_normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm < 1e-9:
        return v
    return [x / norm for x in v]


# ---------------------------------------------------------------------------
# GGUF 자동 다운로드
# ---------------------------------------------------------------------------

# 기본 다운로드 위치: 사용자 캐시 디렉터리(홈 비종속). XDG_CACHE_HOME 존중.
# LOCAL_GGUF_PATH 로 임의 경로를 직접 지정하면 이 기본값을 무시한다.
_DEFAULT_GGUF_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "opencrab", "models",
)
_HF_REPO = "mykor/KURE-v1-gguf"
_HF_FILENAME = "KURE-v1-Q4_K_M.gguf"
# Q4_K_M 선택 이유: Q8_0(600MB, ~0.7s/건) 대비 크기 438MB·속도 ~0.45s/건.
# 폴백은 primary 장애 시 비상용이라 약간의 품질 손실(~2%) 감수.
# LOCAL_GGUF_PATH 로 Q8_0 등 다른 양자화를 직접 지정할 수도 있음.


def _ensure_local_gguf(requested_path: str) -> str:
    """GGUF 파일이 없으면 HuggingFace 에서 자동 다운로드.

    Parameters
    ----------
    requested_path : str
        LOCAL_GGUF_PATH 설정값. 비어있거나 파일이 없으면 기본 경로에 다운로드.

    Returns
    -------
    str
        사용 가능한 GGUF 파일 경로.

    Raises
    ------
    RuntimeError
        다운로드 실패 시 안내 메시지 포함.
    """
    default_path = os.path.join(_DEFAULT_GGUF_DIR, _HF_FILENAME)
    target = requested_path if requested_path else default_path

    if os.path.exists(target):
        return target

    logger.warning(
        "로컬 KURE GGUF 파일이 없습니다: %s\n"
        "  HuggingFace(%s)에서 자동 다운로드를 시도합니다...\n"
        "  수동 다운로드: huggingface-cli download %s %s --local-dir %s\n"
        "  또는 환경변수 LOCAL_GGUF_PATH 에 기존 GGUF 경로를 지정하세요.",
        target, _HF_REPO, _HF_REPO, _HF_FILENAME, _DEFAULT_GGUF_DIR,
    )

    try:
        from huggingface_hub import hf_hub_download  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            f"KURE GGUF 자동 다운로드 실패: huggingface_hub 미설치.\n"
            f"  pip install huggingface_hub 후 재시도하거나\n"
            f"  huggingface-cli download {_HF_REPO} {_HF_FILENAME} "
            f"--local-dir {_DEFAULT_GGUF_DIR} 로 수동 다운로드하세요."
        ) from exc

    try:
        os.makedirs(os.path.dirname(target) or _DEFAULT_GGUF_DIR, exist_ok=True)
        downloaded = hf_hub_download(
            repo_id=_HF_REPO,
            filename=_HF_FILENAME,
            local_dir=os.path.dirname(target) or _DEFAULT_GGUF_DIR,
        )
        # hf_hub_download 가 다른 이름으로 저장할 수 있으므로 확인
        final = downloaded if os.path.exists(downloaded) else target
        logger.info("KURE GGUF 다운로드 완료: %s", final)
        return final
    except Exception as exc:
        raise RuntimeError(
            f"KURE GGUF 자동 다운로드 실패: {exc}\n"
            f"  수동 다운로드:\n"
            f"    huggingface-cli download {_HF_REPO} {_HF_FILENAME} "
            f"--local-dir {_DEFAULT_GGUF_DIR}\n"
            f"  또는 LOCAL_GGUF_PATH 환경변수에 기존 경로를 지정하세요."
        ) from exc
