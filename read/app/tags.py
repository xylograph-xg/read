"""文献库的 tag：论文关键词（只读，来自卡片）+ 自己打的 tag（可编辑，存小 JSON）。

每个论文目录下放一个 tags.json，跟着卡片走；不改动 card.json 本体。
"""

from __future__ import annotations

import json
import re
import time
from core.api import paths__WorkspacePath as Path

TAGS_FILE = "tags.json"
SPLIT_RE = re.compile(r"[,;，；、|\n]+")


def tags_path(root: str | Path) -> Path:
    return Path(root) / TAGS_FILE


def clean_tag(raw: str) -> str:
    tag = re.sub(r"\s+", " ", str(raw)).strip().strip("#")
    return tag[:40]


def split_keywords(raw: str) -> list[str]:
    """卡片里的“关键词”字段切成 tag 列表。"""
    if not raw:
        return []
    tags = [clean_tag(part) for part in SPLIT_RE.split(str(raw))]
    return [tag for tag in dict.fromkeys(tags) if tag]


def load_tags(root: str | Path) -> list[str]:
    path = tags_path(root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        import warnings
        warnings.warn(f"标签文件损坏，原文件保留：{path}: {exc}",RuntimeWarning)
        return []
    values = data.get("tags") if isinstance(data, dict) else data
    if not isinstance(values, list):
        return []
    return [tag for tag in dict.fromkeys(clean_tag(v) for v in values) if tag]


def save_tags(root: str | Path, tags: list[str]) -> None:
    cleaned = [tag for tag in dict.fromkeys(clean_tag(v) for v in tags) if tag]
    from read.api import atomic_io__atomic_json as atomic_json
    atomic_json(tags_path(root),{"tags":cleaned,"updated_at":time.strftime("%Y-%m-%d %H:%M:%S")})
