from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from worker.core.database import get_session

os.environ.setdefault("TC_STUDIO_WORKER_TOKEN", "test-worker-token")

from worker.main import app
from worker.core.security import WORKER_TOKEN_HEADER

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FIXTURES = os.path.join(ROOT, "fixtures")
EXCEL_FIXTURE = os.path.join(FIXTURES, "sample_cases.xlsx")


@pytest.fixture()
def client(tmp_path) -> Generator[TestClient, None, None]:
    os.environ["TC_STUDIO_DATA_DIR"] = str(tmp_path)

    import worker.core.database as database

    database.engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}", echo=False)
    SQLModel.metadata.create_all(database.engine)

    def override_get_session():
        with Session(database.engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, headers={WORKER_TOKEN_HEADER: "test-worker-token"}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def project_id(client: TestClient) -> str:
    response = client.post("/projects", json={"name": "E2E Project"})
    assert response.status_code == 200
    return response.json()["id"]


@pytest.fixture()
def imported_case(client: TestClient, project_id: str) -> dict:
    if not os.path.exists(EXCEL_FIXTURE):
        pytest.skip(f"Missing Excel fixture: {EXCEL_FIXTURE}")
    response = client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": EXCEL_FIXTURE},
    )
    assert response.status_code == 200
    cases = response.json()
    assert cases
    return cases[0]
