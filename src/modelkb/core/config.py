"""Typed configuration: YAML file + environment variables + .env.

Precedence (highest wins): process env > .env > YAML config file > defaults.
Every env var is prefixed ``KB_``; nested settings use ``__``,
e.g. ``KB_VLLM__BASE_URL=http://vllm.internal:8000/v1``.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# Point at a different YAML config file without code changes (ops/tests).
CONFIG_YAML_ENV = "KB_CONFIG_YAML"

# --------------------------------------------------------------------------- #
# Sub-settings                                                                 #
# --------------------------------------------------------------------------- #


class PathsSettings(BaseModel):
    """Filesystem locations. All relative paths resolve against the project root."""

    input_dir: Path = Path("var/input")  # local mirror of the SharePoint folder
    archive_dir: Path = Path("var/archive")  # immutable, sha256-addressed
    extractions_dir: Path = Path("var/extractions")  # deterministic extraction packages
    knowledge_dir: Path = Path("knowledge")  # reviewable Markdown/YAML + schema files
    output_repo_path: Path = Path("var/output")  # future: publishable knowledge repo


class DatabaseSettings(BaseModel):
    # PostgreSQL DSN in real environments, e.g.
    #   postgresql+psycopg://kb:***@host:5432/modelkb
    # SQLite is supported for local development and the test-suite only.
    url: str = "sqlite:///var/modelkb.db"
    echo: bool = False


class VllmSettings(BaseModel):
    """vLLM chat-completions endpoint. Two backends are supported:

    * ``direct``     — OpenAI-compatible server with native structured outputs
                       (vLLM guided decoding via response_format json_schema).
    * ``chat_only``  — chat-only deployment (e.g. the company gateway): the
                       provider emulates structured output with JSON-only
                       prompting, one repair round-trip, and strict parsing.
    """

    backend: str = Field(default="chat_only", pattern="^(chat_only|direct)$")
    base_url: str = "http://127.0.0.1:8000/v1"
    model: str = "qwen3-32b-instruct"
    api_key: str | None = None  # company deployment needs none; direct may
    timeout_s: float = 600.0
    max_retries: int = 2
    temperature: float = 0.0


class CodeSettings(BaseModel):
    repo_path: Path | None = None  # existing local clone takes precedence
    repo_url: str | None = None  # cloned if repo_path is absent
    git_tag: str = "v1.0.0"  # the single configured snapshot tag
    workdir: Path = Path("var/code-repo")  # clone destination when using repo_url


class SharePointSettings(BaseModel):
    """Placeholder for the future Microsoft Graph adapter (polling/delta).

    The initial pipeline reads from ``paths.input_dir`` — a local mirror of the
    SharePoint folder. These fields document and pre-wire the future adapter.
    """

    enabled: bool = False
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    site_url: str | None = None  # e.g. https://tenant.sharepoint.com/sites/models
    drive_path: str | None = None  # e.g. /Model Documentation
    poll_interval_s: int = 900


class ParserSettings(BaseModel):
    """Deterministic PDF extraction knobs."""

    heading_numbered_pattern: str = r"^\d+(\.\d+)*[.)]?\s+\S"
    min_heading_font_ratio: float = 1.15  # span size / body size to count as heading
    table_header_max_rows: int = 2
    equation_min_symbols: int = 2  # math-ish chars required for an equation block
    code_reference_patterns: list[str] = Field(
        default_factory=lambda: [
            r"`(?P<path>[\w./-]+\.py)(?:::?(?P<symbol>[\w.]+))?`",
            r"(?P<path>(?:models|model_lib|src)/[\w./-]+\.py)(?:::?(?P<symbol>[\w.]+))?",
            r"\b(?P<symbol>[a-z_][\w]*(?:\.[a-z_][\w]*){2,})\b",  # dotted.python.symbol
        ]
    )
    citation_year_range: tuple[int, int] = (1950, 2100)


class SchemaSettings(BaseModel):
    active_version: str | None = None  # e.g. "corpus-schema-v1"; set after approval


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KB_",
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="config/settings.yaml",
        extra="ignore",
    )

    environment: str = "dev"
    paths: PathsSettings = Field(default_factory=PathsSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    vllm: VllmSettings = Field(default_factory=VllmSettings)
    code: CodeSettings = Field(default_factory=CodeSettings)
    sharepoint: SharePointSettings = Field(default_factory=SharePointSettings)
    parser: ParserSettings = Field(default_factory=ParserSettings)
    # Named schema_ because BaseSettings reserves .schema(); the YAML key and
    # env prefix remain "schema" (KB_SCHEMA__ACTIVE_VERSION).
    schema_: SchemaSettings = Field(default_factory=SchemaSettings, validation_alias="schema")

    # Source precedence for relationship assertions. Higher wins in the
    # deterministic current-view resolver; nothing is ever deleted.
    source_precedence: dict[str, int] = Field(
        default_factory=lambda: {"human": 100, "pdf": 20, "model_info_json": 10}
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_override = os.environ.get(CONFIG_YAML_ENV)
        yaml_source = (
            YamlConfigSettingsSource(settings_cls, yaml_file=yaml_override)
            if yaml_override
            else YamlConfigSettingsSource(settings_cls)
        )
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            yaml_source,
            file_secret_settings,
        )


_SETTINGS: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _SETTINGS
    if _SETTINGS is None or refresh:
        _SETTINGS = Settings()
    return _SETTINGS


def resolve_path(path: Path, *, root: Path | None = None) -> Path:
    """Resolve a configured path against the project root (cwd by default)."""
    if path.is_absolute():
        return path
    return (root or Path.cwd()) / path
