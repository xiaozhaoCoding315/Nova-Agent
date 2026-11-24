"""Validate thesis template JSON files against thesis-templates/schema.json.

Run from the backend directory:

    python -m scripts.validate_thesis_templates
"""
from __future__ import annotations

import sys

from app.core.thesis.template_validate import validate_templates


def main() -> int:
    errors = validate_templates()
    if errors:
        print("模板校验失败：")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("模板校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
