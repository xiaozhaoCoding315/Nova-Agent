"""Export or verify the committed OpenAPI contract.

Usage:
  python -m scripts.export_openapi            # write contracts/openapi.json
  python -m scripts.export_openapi --check    # exit 1 when the file is stale
"""
import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402

CONTRACT = ROOT / "contracts" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", default=str(CONTRACT))
    args = parser.parse_args()

    payload = render()
    out = Path(args.out)
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current == payload:
            print(f"contract up to date: {out}")
            return 0
        diff = list(difflib.unified_diff(
            current.splitlines(), payload.splitlines(),
            fromfile=str(out), tofile="generated", lineterm="",
        ))
        print("\n".join(diff[:120]))
        print("contract is stale; run python -m scripts.export_openapi")
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
