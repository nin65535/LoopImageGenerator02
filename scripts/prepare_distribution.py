"""Package the built UI and Python runtime sources without local user data."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def prepare(root: Path, output: Path) -> Path:
    files = [
        root / name for name in ("README.md", "requirements.txt", "config.toml", "sql/schema.sql")
    ]
    files += sorted((root / "backend").glob("*.py"))
    files += sorted(path for path in (root / "frontend/dist").rglob("*") if path.is_file())
    files += [root / "documents/ACCEPTANCE.md"]
    files += sorted(path for path in root.glob("*.md") if path.name != "README.md")
    files += sorted(
        path for path in (root / "documents").glob("*.md") if path.name != "ACCEPTANCE.md"
    )
    if not (root / "frontend/dist/index.html").is_file():
        raise ValueError("Build frontend/dist before packaging")
    if any(not path.is_file() for path in files):
        raise ValueError("Required runtime or acceptance files are missing")
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves an existing artifact even with concurrent invocations.
    with output.open("xb") as stream, ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/LoopImageGeneratorV2.zip")
    args = parser.parse_args()
    print(prepare(ROOT, args.output))


if __name__ == "__main__":
    main()
