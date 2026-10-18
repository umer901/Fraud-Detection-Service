import pytest
from fastapi.testclient import TestClient

from fraud_service.app import create_app
from fraud_service.config import Settings
from fraud_service.repository import Repository


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_path=tmp_path / "fraud.db",
        investigation_mode="demo",
        groq_api_key="",
    )


@pytest.fixture
def repository(settings):
    repo = Repository(settings.database_path)
    repo.initialize()
    return repo


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
