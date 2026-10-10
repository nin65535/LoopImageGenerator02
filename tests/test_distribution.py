from zipfile import ZipFile

import pytest

from scripts.prepare_distribution import prepare


def test_runtime_archive_excludes_user_data_and_preserves_existing_output(tmp_path):
    root = tmp_path / "source"
    for name in (
        "README.md",
        "requirements.txt",
        "config.toml",
        "sql/schema.sql",
        "backend/main.py",
        "backend/__pycache__/secret.pyc",
        "frontend/dist/index.html",
        "frontend/dist/assets/app.js",
        "documents/ACCEPTANCE.md",
        "data/private.sqlite3",
        ".env",
        "frontend/node_modules/private.txt",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    output = tmp_path / "runtime.zip"
    prepare(root, output)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "README.md",
            "requirements.txt",
            "config.toml",
            "sql/schema.sql",
            "backend/main.py",
            "frontend/dist/index.html",
            "frontend/dist/assets/app.js",
            "documents/ACCEPTANCE.md",
        }
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        prepare(root, output)
    assert output.read_bytes() == original


def test_distribution_requires_built_ui(tmp_path):
    with pytest.raises(ValueError, match="Build"):
        prepare(tmp_path, tmp_path / "missing.zip")
