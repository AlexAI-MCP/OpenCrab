"""
OpenCrab configuration via Pydantic Settings.

All values can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Local storage. LocalCrab intentionally runs without managed service
    # dependencies; all default stores live under LOCAL_DATA_DIR.
    # ------------------------------------------------------------------
    local_data_dir: str = Field(default="./opencrab_data", alias="LOCAL_DATA_DIR")

    # ------------------------------------------------------------------
    # Optional Neo4j replay/export settings for pack verification.
    # Normal LocalCrab operation does not require a Neo4j server.
    # ------------------------------------------------------------------
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="opencrab", alias="NEO4J_PASSWORD")
    neo4j_database: str | None = Field(default=None, alias="NEO4J_DATABASE")

    # ------------------------------------------------------------------
    # Legacy external-store settings retained for direct adapter use.
    # The default LocalCrab factory path uses local JSON and SQLite stores.
    # ------------------------------------------------------------------
    mongodb_uri: str = Field(
        default="mongodb://root:opencrab@localhost:27017",
        alias="MONGODB_URI",
    )
    mongodb_db: str = Field(default="opencrab", alias="MONGODB_DB")

    # ------------------------------------------------------------------
    postgres_url: str = Field(
        default="postgresql://opencrab:opencrab@localhost:5432/opencrab",
        alias="POSTGRES_URL",
    )

    # ------------------------------------------------------------------
    # ChromaDB local persistent collection.
    # ------------------------------------------------------------------
    chroma_host: str = Field(default="localhost", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8000, alias="CHROMA_PORT")
    chroma_collection: str = Field(
        default="opencrab_vectors", alias="CHROMA_COLLECTION"
    )

    # ------------------------------------------------------------------
    # 임베딩 백엔드 (EMBEDDING_BACKEND 환경변수)
    #
    # 옵션:
    #   "local"  — ChromaDB 기본 EF (all-MiniLM-L6-v2, ONNX, 384d, 영어특화).
    #              기존 동작 그대로. CHROMA_COLLECTION("opencrab_vectors") 사용.
    #              llama-cpp-python / 외부 서버 불필요. 롤백 기본값.
    #   "openai" — OpenAI 호환 임베딩 서버(LM Studio·Ollama·vLLM·OpenAI 등) +
    #              로컬 GGUF 폴백 자동 전환. EMBED_COLLECTION 컬렉션 사용.
    #              실측(KURE-v1): top-1 5/5, MRR 1.000 vs minilm top-1 0/5, MRR 0.285.
    #
    # 변경 이유: 한국어 검색 품질 개선. minilm 은 한국어 변별 실패 수준.
    # 롤백: EMBEDDING_BACKEND 미설정 또는 "local" 로 되돌리면 기존 컬렉션 그대로.
    # ------------------------------------------------------------------
    embedding_backend: str = Field(
        default="local",
        alias="EMBEDDING_BACKEND",
        # Literal["local", "openai"] — pydantic-settings 호환을 위해 str 사용
    )

    # OpenAI 호환 임베딩 서버 설정 (EMBEDDING_BACKEND=openai 시 사용)
    # LM Studio, Ollama, vLLM, 실제 OpenAI 등 /v1/embeddings 구현 서버 모두 호환.
    # 대안: openai 패키지 미설치라 httpx 직접 호출 방식 채택.
    openai_api_base: str = Field(
        default="http://localhost:1234/v1",
        alias="OPENAI_API_BASE",
    )
    # 서버에 로드된 임베딩 모델 id. /v1/models 로 확인.
    # 예: "text-embedding-kure-v1" (KURE-v1), "text-embedding-3-small" 등
    openai_embed_model: str = Field(
        default="text-embedding-kure-v1",
        alias="OPENAI_EMBED_MODEL",
    )
    # OpenAI API key. 실제 OpenAI / 인증 게이트웨이 사용 시 설정.
    # 미설정(빈 문자열)이면 Authorization 헤더 없이 호출(LM Studio 등 무인증 서버).
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    # 임베딩 차원. 사용 모델에 맞게 설정. 변경 시 컬렉션 재적재 필요.
    # KURE-v1 = 1024, multilingual-e5-small = 384, text-embedding-3-small = 1536.
    embed_dim: int = Field(default=1024, alias="EMBED_DIM")

    # OpenAI 호환 서버 HTTP 타임아웃(초). 기본 8s.
    # 로컬 네트워크 기준 정상 응답은 1-3s이므로 8s면 충분.
    # 느린 원격 네트워크나 대형 배치 요청이라면 OPENAI_TIMEOUT 환경변수로 늘릴 것.
    openai_timeout: float = Field(default=8.0, alias="OPENAI_TIMEOUT")

    # openai 백엔드 전용 Chroma 컬렉션명. minilm("opencrab_vectors")와 분리해
    # 차원 비호환 문제를 방지한다. 롤백 시 기존 컬렉션은 보존됨.
    embed_collection: str = Field(
        default="opencrab_vectors_kure",
        alias="EMBED_COLLECTION",
    )

    # 로컬 GGUF 경로 (EMBEDDING_BACKEND=openai 시 폴백용).
    # 미설정 시 _ensure_local_gguf() 가 자동 다운로드(KURE-v1-Q4_K_M, ~438MB).
    # 다른 모델을 쓰려면 LOCAL_GGUF_PATH 로 직접 경로 지정.
    local_gguf_path: str = Field(default="", alias="LOCAL_GGUF_PATH")

    # ------------------------------------------------------------------
    # MCP server
    # ------------------------------------------------------------------
    mcp_server_name: str = Field(default="opencrab", alias="MCP_SERVER_NAME")
    mcp_server_version: str = Field(default="0.1.0", alias="MCP_SERVER_VERSION")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    @property
    def is_local(self) -> bool:
        return True

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.local_data_dir}/opencrab.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
