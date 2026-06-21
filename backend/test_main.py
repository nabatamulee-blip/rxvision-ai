import pytest
from fastapi.testclient import TestClient
from main import app, get_db, SessionLocal, Base, engine

Base.metadata.create_all(bind=engine)

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "RxVision AI"}

def test_list_records(client):
    response = client.get("/records")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
