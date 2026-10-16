from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_create_and_get_listing():
    payload = {
        "title": "Test flat",
        "address": "1 Main St",
        "city": "Boston",
        "price": "2500.00",
        "bedrooms": 2,
        "bathrooms": 1,
    }
    created = client.post("/api/listings", json=payload)
    assert created.status_code == 201
    listing_id = created.json()["id"]

    fetched = client.get(f"/api/listings/{listing_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Test flat"

    assert client.delete(f"/api/listings/{listing_id}").status_code == 204
