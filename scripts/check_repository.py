"""Check the stage-01 repository structure and local Markdown links."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "README.md",
    "AGENTS.md",
    "SPEC.md",
    "ARCHITECTURE.md",
    "documents/PROJECT_PLAN.md",
    "documents/IMPLEMENTATION.md",
    "documents/ROADMAP.md",
    "sql/schema.sql",
    ".gitignore",
)
REQUIRED_DIRECTORIES = ("backend", "frontend", "tests", "scripts")


def main() -> int:
    errors = []
    for name in REQUIRED_FILES:
        if not (ROOT / name).is_file():
            errors.append(f"Missing file: {name}")
    for name in REQUIRED_DIRECTORIES:
        if not (ROOT / name).is_dir():
            errors.append(f"Missing directory: {name}")

    documents = list(ROOT.glob("*.md")) + list((ROOT / "documents").glob("*.md"))
    for document in documents:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            local_path = target.split("#", 1)[0]
            if local_path and not (document.parent / local_path).exists():
                errors.append(f"Broken link in {document.relative_to(ROOT)}: {target}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Repository structure and local Markdown links: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
