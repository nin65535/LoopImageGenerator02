from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


def test_health_without_frontend(tmp_path):
    with TestClient(
        create_app(tmp_path / "missing", settings=Settings(storage_dir=tmp_path / "data"))
    ) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "app": "LoopImageGenerator V2"}
        assert client.get("/").status_code == 404


def test_static_delivery_preserves_api(tmp_path):
    (tmp_path / "index.html").write_text('<div id="root">UI</div>', encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('UI')", encoding="utf-8")
    with TestClient(
        create_app(tmp_path, settings=Settings(storage_dir=tmp_path / "data"))
    ) as client:
        assert 'id="root"' in client.get("/").text
        assert client.get("/app.js").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/missing").status_code == 404
        assert client.get("/missing.js").status_code == 404
