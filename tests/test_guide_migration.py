from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from packages.database.models import IPO
from packages.shared.config import settings


def test_guide_migration_preserves_existing_ipo_and_matches_models(tmp_path, monkeypatch):
    path = tmp_path / "migration.db"
    monkeypatch.setattr(settings(), "database_url", f"sqlite+aiosqlite:///{path.as_posix()}")
    config = Config("alembic.ini")
    command.upgrade(config, "98017c9d7309")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO companies (id, slug, name, board, is_demo, created_at, updated_at) VALUES ('old-company', 'migration-company', 'Migration company', 'Mainboard', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ipos (id, company_id, status, quality, price_high, lot_size, created_at, updated_at) VALUES ('old-ipo', 'old-company', 'UPCOMING', 'UNVERIFIED', 150, 50, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    assert "ipo_applicant_guides" in inspect(engine).get_table_names()
    with Session(engine) as db:
        assert db.scalar(select(IPO.price_high)) == 150
    command.downgrade(config, "98017c9d7309")
    assert "ipo_applicant_guides" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    engine.dispose()
