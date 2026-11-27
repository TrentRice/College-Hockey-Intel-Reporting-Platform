"""?league= on the API (src/api/db.py): a server without a league's data says so."""

from fastapi.testclient import TestClient

from src.api.main import create_app


def test_league_routing(database_url):
    app = create_app(database_url=database_url, api_key="k")  # men's database only
    with TestClient(app) as c:
        h = {"X-API-Key": "k"}
        assert c.get("/v1/seasons", headers=h).status_code == 200  # men's by default
        assert c.get("/v1/seasons", params={"league": "men"}, headers=h).status_code == 200
        women = c.get("/v1/seasons", params={"league": "women"}, headers=h)
        assert women.status_code == 503 and "women" in women.json()["detail"]
        assert c.get("/v1/seasons", params={"league": "coed"}, headers=h).status_code == 422
