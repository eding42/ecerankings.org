"""Central field registry loader and helper for multi-discipline rankings.

Defines the fields, directory paths, and capability flags across all
supported ranking disciplines (ECE, Biology, Earth & Space).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FIELDS_PATH = os.path.join(REPO_ROOT, "data", "fields.json")


@dataclass
class FieldConfig:
    id: str
    name: str
    short_name: str
    description: str
    site_dir: str
    site_data_dir: str
    areas_file: str
    cache_dir: str
    default_credit_types: List[str]
    earliest_year: int
    default_start_year: int
    default_end_year: int
    capabilities: Dict[str, Any] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    repo_root: str = REPO_ROOT

    def path(self, relative_path: str) -> str:
        """Resolve a repo-relative path against this field's repo root."""
        return os.path.join(self.repo_root, relative_path)

    @property
    def areas_path(self) -> str:
        return self.path(self.areas_file)

    @property
    def cache_path(self) -> str:
        return self.path(self.cache_dir)

    @property
    def site_path(self) -> str:
        return self.path(self.site_dir)

    @property
    def site_data_path(self) -> str:
        return self.path(self.site_data_dir)

    def has_capability(self, key: str, default: bool = False) -> bool:
        return bool(self.capabilities.get(key, default))


def load_fields(
    config_path: Optional[str] = None,
    repo_root: Optional[str] = None
) -> Dict[str, FieldConfig]:
    """Load all configured fields from data/fields.json."""
    root = repo_root or REPO_ROOT
    path = config_path or os.path.join(root, "data", "fields.json")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_fields = data.get("fields", {})
    fields: Dict[str, FieldConfig] = {}

    for fid, cfg in raw_fields.items():
        fields[fid] = FieldConfig(
            id=cfg.get("id", fid),
            name=cfg.get("name", fid),
            short_name=cfg.get("short_name", fid),
            description=cfg.get("description", ""),
            site_dir=cfg.get("site_dir", f"site/{fid}"),
            site_data_dir=cfg.get("site_data_dir", f"site/{fid}/data"),
            areas_file=cfg.get("areas_file", f"data/areas_{fid}.json"),
            cache_dir=cfg.get("cache_dir", "cache"),
            default_credit_types=list(cfg.get("default_credit_types", ["education"])),
            earliest_year=int(cfg.get("earliest_year", 2016)),
            default_start_year=int(cfg.get("default_start_year", 2016)),
            default_end_year=int(cfg.get("default_end_year", 2025)),
            capabilities=dict(cfg.get("capabilities", {})),
            aliases=list(cfg.get("aliases", [fid])),
            repo_root=root,
        )

    return fields


def get_field(
    field_id_or_alias: str,
    config_path: Optional[str] = None,
    repo_root: Optional[str] = None
) -> FieldConfig:
    """Retrieve FieldConfig by its primary id or registered alias."""
    fields = load_fields(config_path=config_path, repo_root=repo_root)
    normalized = field_id_or_alias.strip().lower()

    if normalized in fields:
        return fields[normalized]

    for cfg in fields.values():
        if normalized in [a.lower() for a in cfg.aliases]:
            return cfg

    valid_choices = list_field_ids(config_path=config_path, repo_root=repo_root)
    raise KeyError(f"Unknown field '{field_id_or_alias}'. Valid fields: {', '.join(valid_choices)}")


def list_field_ids(
    config_path: Optional[str] = None,
    repo_root: Optional[str] = None
) -> List[str]:
    """Return all primary field ids sorted."""
    fields = load_fields(config_path=config_path, repo_root=repo_root)
    return sorted(fields.keys())


def add_field_argument(
    parser: argparse.ArgumentParser,
    default: Optional[str] = None,
    required: bool = False,
    help_text: Optional[str] = None,
) -> None:
    """Add a standardized --field CLI flag to an ArgumentParser."""
    available = list_field_ids()
    help_msg = help_text or f"Discipline field identifier (choices: {', '.join(available)})"
    if default:
        help_msg += f" [default: {default}]"

    parser.add_argument(
        "--field",
        dest="field",
        type=str,
        default=default,
        required=required,
        help=help_msg,
    )
