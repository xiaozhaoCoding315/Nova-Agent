"""Skill system: SKILL.md playbooks with trigger-based injection."""
from app.core.skills.loader import (
    Skill,
    build_skill_prompt,
    load_skills,
    match_skills,
    skills_root,
)

__all__ = ["Skill", "build_skill_prompt", "load_skills", "match_skills", "skills_root"]
