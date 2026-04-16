"""
OpenCrab configuration via Pydantic Settings.

All values can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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
    # Storage mode: "local" (no Docker) or "docker" (full services)
    # ------------------------------------------------------------------
    storage_mode: Literal["local", "docker"] = Field(
        default="local", alias="STORAGE_MODE"
    )
    local_data_dir: str = Field(default="./opencrab_data", alias="LOCAL_DATA_DIR")

    # ------------------------------------------------------------------
    # Neo4j (docker mode only)
    # ------------------------------------------------------------------
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="opencrab", alias="NEO4J_PASSWORD")
    neo4j_database: str | None = Field(default=None, alias="NEO4J_DATABASE")

    # ------------------------------------------------------------------
    # MongoDB (docker mode only)
    # ------------------------------------------------------------------
    mongodb_uri: str = Field(
        default="mongodb://root:opencrab@localhost:27017",
        alias="MONGODB_URI",
    )
    mongodb_db: str = Field(default="opencrab", alias="MONGODB_DB")

    # ------------------------------------------------------------------
    # PostgreSQL (docker mode) / SQLite (local mode)
    # ------------------------------------------------------------------
    postgres_url: str = Field(
        default="postgresql://opencrab:opencrab@localhost:5432/opencrab",
        alias="POSTGRES_URL",
    )

    # ------------------------------------------------------------------
    # ChromaDB (docker mode uses HttpClient; local mode uses PersistentClient)
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
        return self.storage_mode == "local"

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.local_data_dir}/opencrab.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
