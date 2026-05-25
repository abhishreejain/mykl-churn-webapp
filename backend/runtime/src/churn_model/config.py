"""Configuration loading and path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


class DecisionRequired(RuntimeError):
    """Raised when a business rule checkpoint has not been configured."""


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries without mutating inputs."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class ProjectConfig:
    """Resolved project configuration."""

    root: Path
    values: dict[str, Any]

    def get(self, dotted_key: str, default: Any = None) -> Any:
        current: Any = self.values
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def path(self, dotted_key: str) -> Path:
        raw = self.get(dotted_key)
        if raw is None:
            raise ConfigError(f"Missing path config: {dotted_key}")
        path = Path(str(raw))
        return path if path.is_absolute() else self.root / path

    def ensure_dirs(self) -> None:
        for key in (
            "paths.reports_dir",
            "paths.artifacts_dir",
            "paths.production_artifacts_dir",
            "paths.experiment_artifacts_dir",
            "paths.processed_data_dir",
            "paths.modeling_data_dir",
            "paths.outputs_dir",
        ):
            self.path(key).mkdir(parents=True, exist_ok=True)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config must be a mapping: {path}")
    return data


def load_config(
    config_path: str | Path = "configs/base.yaml",
    business_rules_path: str | Path | None = None,
    root: str | Path | None = None,
) -> ProjectConfig:
    """Load base config and optional business rules config."""
    project_root = Path(root or ".").resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = project_root / config_file
    values = load_yaml(config_file)

    if business_rules_path:
        rules_file = Path(business_rules_path)
        if not rules_file.is_absolute():
            rules_file = project_root / rules_file
        values = deep_merge(values, load_yaml(rules_file))

    cfg = ProjectConfig(root=project_root, values=values)
    cfg.ensure_dirs()
    return cfg
