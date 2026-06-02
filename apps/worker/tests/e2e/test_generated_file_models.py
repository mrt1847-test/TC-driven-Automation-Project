"""A2-11: GeneratedFile origin/hash/status metadata is durable."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlmodel import Session, select

from worker.models.db import GeneratedFile, GeneratedFileOrigin


def test_generated_file_origin_hash_and_status_metadata_persist(project_id: str) -> None:
    import worker.core.database as database

    inspector = inspect(database.engine)
    assert "generated_file_origins" in inspector.get_table_names()
    generated_file_columns = {column["name"] for column in inspector.get_columns(GeneratedFile.__tablename__)}
    assert {"source_type", "source_id", "content_hash", "status"}.issubset(generated_file_columns)

    with Session(database.engine) as session:
        generated_file = GeneratedFile(
            id="gf_login_flow",
            project_id=project_id,
            relative_path="flows/login_flow.py",
            automation_key="login_flow",
            source_type="structured_flow",
            source_id="sf_login_001",
            content_hash="sha256:abc123",
            status="generated",
        )
        session.add(generated_file)
        session.add(GeneratedFileOrigin(
            generated_file_id=generated_file.id,
            origin_type="structured_flow",
            origin_id="sf_login_001",
        ))
        session.add(GeneratedFileOrigin(
            generated_file_id=generated_file.id,
            origin_type="page_object_method",
            origin_id="pom_submit_login",
        ))
        session.commit()

    with Session(database.engine) as session:
        saved_file = session.get(GeneratedFile, "gf_login_flow")
        assert saved_file is not None
        assert saved_file.source_type == "structured_flow"
        assert saved_file.source_id == "sf_login_001"
        assert saved_file.content_hash == "sha256:abc123"
        assert saved_file.status == "generated"

        origins = session.exec(
            select(GeneratedFileOrigin)
            .where(GeneratedFileOrigin.generated_file_id == saved_file.id)
            .order_by(GeneratedFileOrigin.origin_type, GeneratedFileOrigin.origin_id)
        ).all()

    assert [(origin.origin_type, origin.origin_id) for origin in origins] == [
        ("page_object_method", "pom_submit_login"),
        ("structured_flow", "sf_login_001"),
    ]
