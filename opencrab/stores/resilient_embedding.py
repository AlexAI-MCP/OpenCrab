"""
ResilientEmbeddingFunction — 원격 서버 ↔ 로컬 GGUF 자동 폴백 EF

변경 이유:
  - 원격 OpenAI 호환 임베딩 서버(primary)가 재시작/점검 중일 때도 검색이 멈추지
    않도록, 동일 모델(KURE-v1)의 로컬 GGUF 를 폴백으로 자동 사용.
  - 한 번 ping 실패 시 health_ttl 동안 primary 를 건너뛰어 불필요한
    30s 타임아웃 대기를 방지.

동작 원칙:
  - primary 임베딩 호출 성공 → 정상 반환.
  - primary 에서 예외 발생 → 경고 로그 후 fallback 호출.
  - health_ttl(기본 15s) 동안 primary 장애 캐시 → 불필요한 재시도 방지.
  - 이름(name())은 primary 와 동일하게 "kure_v1" 반환 → 컬렉션 재사용 보장.

대안:
  - Circuit breaker 패턴: health_ttl 대신 실패 횟수 기반.
    구현 복잡도 대비 이득이 적어 TTL 방식 채택.
  - 프로세스 재시작 시 헬스 캐시 초기화됨 → primary 가 살아있으면
    다음 호출에서 바로 복귀.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_UNHEALTHY_UNTIL_ATTR = "_unhealthy_until"


class ResilientEmbeddingFunction:
    """primary EF 장애 시 fallback EF 로 자동 전환.

    Parameters
    ----------
    primary : Any
        정상 운용 EF. OpenAIEmbeddingFunction 권장.
    fallback : Any
        primary 장애 시 사용하는 EF. LlamaCppEmbeddingFunction 권장.
    health_ttl : float
        primary 장애 후 재시도 금지 시간(초). 기본 15s.
        낮추면 빠른 복귀, 높이면 타임아웃 낭비 감소.
    """

    def __init__(
        self,
        primary: Any,
        fallback: Any,
        health_ttl: float = 15.0,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._health_ttl = health_ttl
        self._unhealthy_until: float = 0.0  # epoch seconds

    # ------------------------------------------------------------------
    # ChromaDB EmbeddingFunction 프로토콜
    # ------------------------------------------------------------------

    def __call__(self, input: list[str]) -> list[list[float]]:
        """primary 시도 → 실패 시 fallback."""
        if not input:
            return []

        if self._primary_is_healthy():
            try:
                result = self._primary(input)
                return result
            except Exception as exc:
                logger.warning(
                    "원격 임베딩 서버 호출 실패 (%s) → 로컬 GGUF 폴백 사용",
                    exc,
                )
                self._mark_unhealthy()

        # fallback 경로
        logger.info("임베딩 폴백: 로컬 GGUF (원격 서버 장애 또는 unhealthy)")
        return self._fallback(input)

    def name(self) -> str:
        """ChromaDB persistence 식별 이름. primary 와 동일("kure_v1") 반환."""
        return self._primary.name()

    def embed_query(self, input: list[str]) -> list[list[float]]:
        """ChromaDB 1.5+ 가 query 경로에서 호출하는 메서드.
        KURE 는 쿼리/패시지 임베딩이 대칭이므로 __call__ 과 동일 처리."""
        return self.__call__(input)

    # ------------------------------------------------------------------
    # 헬스 TTL 관리
    # ------------------------------------------------------------------

    def _primary_is_healthy(self) -> bool:
        return time.monotonic() >= self._unhealthy_until

    def _mark_unhealthy(self) -> None:
        self._unhealthy_until = time.monotonic() + self._health_ttl
        logger.info(
            "primary(원격 서버) 를 %.0fs 동안 건너뜀 (health_ttl)",
            self._health_ttl,
        )

    def force_check(self) -> bool:
        """수동 헬스체크 후 TTL 초기화 (선택). 운영 스크립트에서 사용 가능."""
        if hasattr(self._primary, "ping") and self._primary.ping():
            self._unhealthy_until = 0.0
            logger.info("primary(원격 서버) 헬스체크 성공 → 폴백 해제")
            return True
        return False
