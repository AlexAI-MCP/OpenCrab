"""
OpenAI 호환 임베딩 EF (ChromaDB EmbeddingFunction 프로토콜)

표준 OpenAI `/v1/embeddings` 엔드포인트를 httpx 로 직접 호출한다. LM Studio,
Ollama, vLLM, Text-Embeddings-Inference, 실제 OpenAI API 등 동일 스펙을 구현한
모든 서버에서 동작한다.

변경 이유:
  - ChromaDB 기본 EF(all-MiniLM-L6-v2, 384d)는 영어 특화라 한국어 검색
    품질이 낮음(실측: top-1 0/5, MRR 0.285).
  - OpenAI 호환 서버에 KURE-v1(1024d, 한국어 SOTA) 등을 서빙해 품질 개선
    (실측: top-1 5/5, MRR 1.000).

대안:
  - openai 패키지 사용: 추가 의존성이 필요해 제외.
  - sentence-transformers 직접: CPU 환경에서 느림 → 로컬 GGUF 폴백으로 대체.
  - httpx 직접 호출(채택): 의존성 최소(httpx 만 사용).

인증:
  - api_key 가 주어지면 Authorization: Bearer 헤더를 보낸다(실제 OpenAI /
    인증 게이트웨이용). 미설정 시 헤더 없이 호출(LM Studio 등 무인증 서버).

롤백:
  - EMBEDDING_BACKEND=local 환경변수로 기존 minilm 경로 즉시 복귀 가능.
"""

import logging
import math
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EMBEDDING_FUNCTION_NAME = "kure_v1"
# ChromaDB 1.5+ 는 get_or_create_collection 시 EF name 으로 컬렉션을
# 재식별한다. 동일 name 을 반환해야 재시작 후에도 컬렉션을 재사용할 수 있다.


class OpenAIEmbeddingFunction:
    """OpenAI 호환 /v1/embeddings 호출 EF.

    Parameters
    ----------
    api_base : str
        예: "http://localhost:1234/v1" 또는 "https://api.openai.com/v1"
    model : str
        임베딩 모델 id. 예: "text-embedding-kure-v1", "text-embedding-3-small"
    dim : int
        임베딩 차원 (KURE = 1024). 검증·로그용; 실제 clip 은 없음.
    timeout : float
        HTTP 타임아웃(초). 기본 30s. 네트워크 지연에 따라 조정.
    batch : int
        한 번에 보낼 최대 문자열 수. 서버 단일 요청 제한에 맞게 조정.
    api_key : str | None
        주어지면 Authorization: Bearer 헤더로 전송. 무인증 서버(LM Studio 등)는
        None(또는 빈 문자열)로 두면 헤더 없이 호출.
    """

    def __init__(
        self,
        api_base: str,
        model: str,
        dim: int = 1024,
        timeout: float = 30.0,
        batch: int = 32,
        api_key: str | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._model = model
        self._dim = dim
        self._timeout = timeout
        self._batch = batch
        self._api_key = api_key or None

    # ------------------------------------------------------------------
    # ChromaDB EmbeddingFunction 프로토콜
    # ------------------------------------------------------------------

    def __call__(self, input: list[str]) -> list[list[float]]:
        """텍스트 리스트 → 임베딩 리스트 (batch 단위 처리)."""
        if not input:
            return []
        result: list[list[float]] = []
        for i in range(0, len(input), self._batch):
            chunk = input[i : i + self._batch]
            result.extend(self._embed_batch(chunk))
        return result

    def name(self) -> str:
        """ChromaDB persistence 에서 EF 를 식별하는 고정 이름."""
        return _EMBEDDING_FUNCTION_NAME

    def embed_query(self, input: list[str]) -> list[list[float]]:
        """ChromaDB 1.5+ 가 query 경로에서 호출하는 메서드.
        KURE 는 쿼리/패시지 임베딩이 대칭이므로 __call__ 과 동일 처리."""
        return self.__call__(input)

    # ------------------------------------------------------------------
    # 헬스체크
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """서버가 응답하면 True. ResilientEF 헬스 TTL 캐시에서 사용."""
        try:
            resp = httpx.get(
                f"{self._api_base}/models",
                headers=self._headers(),
                timeout=5.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """api_key 가 설정된 경우에만 Authorization 헤더를 반환."""
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            f"{self._api_base}/embeddings",
            json={"model": self._model, "input": texts},
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        vecs = [item["embedding"] for item in data["data"]]
        # KURE 등은 이미 L2 정규화된 벡터를 반환하나, 안전하게 재정규화.
        return [_l2_normalize(v) for v in vecs]


def _l2_normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm < 1e-9:
        return v
    return [x / norm for x in v]
