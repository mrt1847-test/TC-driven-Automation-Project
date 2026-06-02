"""A2-12: schema baseline marker is recorded during DB initialization."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlmodel import Session, create_engine, select

from worker.core.database import SCHEMA_VERSION, SCHEMA_VERSION_ID
from worker.models.db import Project, SchemaVersion


def test_init_db_records_schema_version_without_disrupting_existing_tables(tmp_path) -> None:
    import worker.core.database as database

    original_engine = database.engine
    try:
        database.engine = create_engine(f"sqlite:///{tmp_path / 'schema-version.db'}", echo=False)

        database.init_db()

        inspector = inspect(database.engine)
        table_names = inspector.get_table_names()
        assert "schema_versions" in table_names
        assert Project.__tablename__ in table_names

        with Session(database.engine) as session:
            version = session.get(SchemaVersion, SCHEMA_VERSION_ID)
            assert version is not None
            assert version.version == SCHEMA_VERSION
            assert version.description
            assert version.applied_at is not None
            assert version.updated_at is not None

            session.add(Project(id="proj_schema_version", name="Schema Version Project", root_path=str(tmp_path)))
            session.commit()

        database.init_db()

        with Session(database.engine) as session:
            versions = session.exec(select(SchemaVersion)).all()
            assert len(versions) == 1
            assert session.get(Project, "proj_schema_version") is not None
    finally:
        database.engine = original_engine
