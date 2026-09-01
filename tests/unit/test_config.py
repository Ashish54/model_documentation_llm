from pathlib import Path

from modelkb.core.config import Settings


def test_defaults_load() -> None:
    s = Settings(_env_file=None)  # ignore .env / yaml for a pure-default check
    assert s.vllm.backend == "chat_only"
    assert s.source_precedence["pdf"] > s.source_precedence["model_info_json"]
    assert s.code.git_tag


def test_yaml_and_env_precedence(tmp_path: Path, monkeypatch) -> None:
    yaml_cfg = tmp_path / "settings.yaml"
    yaml_cfg.write_text("vllm:\n  model: yaml-model\n  base_url: http://yaml:1/v1\n")
    monkeypatch.setenv("KB_CONFIG_YAML", str(yaml_cfg))
    monkeypatch.setenv("KB_VLLM__BASE_URL", "http://env:2/v1")
    s = Settings(_env_file=None)
    # env beats YAML; YAML beats code default
    assert s.vllm.base_url == "http://env:2/v1"
    assert s.vllm.model == "yaml-model"


def test_schema_alias_keeps_yaml_key(tmp_path: Path, monkeypatch) -> None:
    yaml_cfg = tmp_path / "settings.yaml"
    yaml_cfg.write_text("schema:\n  active_version: corpus-schema-v9\n")
    monkeypatch.setenv("KB_CONFIG_YAML", str(yaml_cfg))
    s = Settings(_env_file=None)
    assert s.schema_.active_version == "corpus-schema-v9"


def test_parser_patterns_are_configurable() -> None:
    s = Settings(_env_file=None)
    assert any(".py" in p for p in s.parser.code_reference_patterns)
