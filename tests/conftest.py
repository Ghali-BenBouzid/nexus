from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from main import app


@pytest.fixture
def client() -> Generator[TestClient]:
    # Setting up the test database and dependency override
    engine = create_engine(
        url="sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def get_test_db() -> Generator[Session]:
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_test_db

    Base.metadata.create_all(bind=engine)  # creating tables

    yield TestClient(app)

    Base.metadata.drop_all(bind=engine)  # dropping all the tables / cleaning
