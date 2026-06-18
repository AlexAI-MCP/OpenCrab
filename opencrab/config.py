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
    # MCP server
    # ------------------------------------------------------------------
    mcp_server_name: str = Field(default="opencrab", alias="MCP_SERVER_NAME")
    mcp_server_version: str = Field(default="0.1.0", alias="MCP_SERVER_VERSION")
    # HTTP transport (opencrab serve --transport http). Bind host defaults to
    # loopback; expose on a trusted network via --host 0.0.0.0. The bearer token
    # is NOT read from config — it comes from --auth-token(-file) or
    # OPENCRAB_MCP_TOKEN(_FILE) to keep secrets out of the settings object.
    mcp_http_host: str = Field(default="127.0.0.1", alias="MCP_HTTP_HOST")
    mcp_http_port: int = Field(default=8765, alias="MCP_HTTP_PORT")

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
