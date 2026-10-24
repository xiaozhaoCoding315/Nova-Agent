"""SKILL.md-style skills: operator-provided playbooks injected on trigger.

Skills live in ``<skills_dir>/<skill-name>/SKILL.md`` with a YAML frontmatter
(``name`` / ``description`` / optional ``triggers``) followed by the manual
body.  Only names and descriptions enter every prompt; the full body is
injected (progressive disclosure) when the user message mentions the skill
name or contains one of its trigger keywords.
"""
import time
from dataclasses import dataclass
from pathlib import Path

import structlog
import yaml

from app.config import settings

logger = structlog.get_logger()

MAX_SKILLS = 30
BODY_MAX_CHARS = 4000
TRIGGER_MAX = 2
SCAN_INTERVAL_S = 30


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    body: str
    path: str


_cache: dict[str, tuple[float, Skill]] = {}
_last_scan: float = 0.0


def _parse_skill_file(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("skill_read_failed", path=str(path), error=str(exc))
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    name = str(meta.get("name") or path.parent.name).strip()
    description = str(meta.get("description") or "").strip()[:300]
    raw_triggers = meta.get("triggers") or []
    if not isinstance(raw_triggers, list):
        raw_triggers = [raw_triggers]
    triggers = tuple(
        str(t).strip().lower() for t in raw_triggers if str(t).strip()
    )[:10]
    body = parts[2].strip()[:BODY_MAX_CHARS]
    if not name or not body:
        return None
    return Skill(
        name=name, description=description, triggers=triggers,
        body=body, path=str(path),
    )


def skills_root() -> Path:
    root = Path(settings.skills_dir)
    return root if root.is_absolute() else Path.cwd() / root


def load_skills(force: bool = False) -> list[Skill]:
    """Scan the skills dir with an mtime-based cache (rescan ≤ every 30s)."""
    global _cache, _last_scan
    if not settings.skills_enabled:
        return []
    root = skills_root()
    if not root.is_dir():
        return []
    now = time.time()
    if not force and _cache and now - _last_scan < SCAN_INTERVAL_S:
        return [skill for _, skill in _cache.values()]
    _last_scan = now
    fresh: dict[str, tuple[float, Skill]] = {}
    for skill_file in sorted(root.glob("*/SKILL.md"))[:MAX_SKILLS]:
        key = str(skill_file)
        try:
            mtime = skill_file.stat().st_mtime
        except OSError:
            continue
        cached = _cache.get(key)
        if cached and cached[0] == mtime:
            fresh[key] = cached
            continue
        skill = _parse_skill_file(skill_file)
        if skill:
            fresh[key] = (mtime, skill)
    _cache = fresh
    return [skill for _, skill in fresh.values()]


def match_skills(message: str, skills: list[Skill]) -> list[Skill]:
    lowered = (message or "").lower()
    matched: list[Skill] = []
    for skill in skills:
        name = skill.name.lower()
        if name and (f"/{name}" in lowered or lowered == name):
            matched.append(skill)
        elif any(t in lowered for t in skill.triggers):
            matched.append(skill)
    return matched[:TRIGGER_MAX]


def build_skill_prompt(message: str) -> str:
    """Index of all skills + full manuals for the triggered ones."""
    skills = load_skills()
    if not skills:
        return ""
    index_lines = [
        f"- {s.name}：{s.description}" if s.description else f"- {s.name}"
        for s in skills
    ]
    parts = [
        "## 可用技能（操作员预置的操作手册，按需参考）",
        "\n".join(index_lines),
        "用户点名技能名（如 /技能名）或问题命中触发词时，必须按对应手册的流程执行。",
    ]
    for skill in match_skills(message, skills):
        parts.append(f"### 技能手册：{skill.name}\n{skill.body}")
    return "\n\n".join(parts)
