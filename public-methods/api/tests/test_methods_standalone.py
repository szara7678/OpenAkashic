from fastapi.testclient import TestClient
from app.methods_main import app


def test_portable_reader_serves_graph_assets_and_no_legacy_ingestion():
    client = TestClient(app)
    for path in ("/research/", "/research/methods-graph.js", "/research/methods.css", "/research/methods-kpi.html", "/research/methods-kpi.js"):
        r = client.get(path)
        assert r.status_code == 200
        assert "no-transform" in r.headers["cache-control"]
        assert "unsafe-inline" not in r.headers["content-security-policy"]
    assert client.post("/research/api/investigations", json={}).status_code == 404
    assert client.get("/research/.env").status_code in (404, 422)


def test_root_and_graph_are_same_read_only_atlas():
    client = TestClient(app, follow_redirects=False)
    pages = [client.get(path) for path in ("/", "/graph", "/graph/", "/research/")]
    assert all(response.status_code == 200 for response in pages)
    assert len({response.content for response in pages}) == 1
    for path in ("/capsules", "/graph-data", "/research/api/search",
                 "/research/api/knowledge", "/research/api/investigations"):
        assert client.get(path).status_code == 404
