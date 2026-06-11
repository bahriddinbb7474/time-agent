import asyncio
from pathlib import Path

import app.main as main_module
from app.db.migration_runner import MigrationRunResult


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def main() -> None:
    calls: list[str] = []

    def fake_run_migrations(db_path):
        assert db_path == Path("data") / "app.db"
        calls.append("migrate")
        return MigrationRunResult(applied=["baseline"], skipped=["stage14"])

    def fake_get_sessionmaker():
        calls.append("sessionmaker")
        return FakeSession

    async def fake_seed_if_empty(session):
        assert isinstance(session, FakeSession)
        calls.append("seed")

    original_run_migrations = main_module.run_migrations
    original_get_sessionmaker = main_module.get_sessionmaker
    original_seed_if_empty = main_module.seed_if_empty

    main_module.run_migrations = fake_run_migrations
    main_module.get_sessionmaker = fake_get_sessionmaker
    main_module.seed_if_empty = fake_seed_if_empty
    try:
        asyncio.run(main_module.init_db())
    finally:
        main_module.run_migrations = original_run_migrations
        main_module.get_sessionmaker = original_get_sessionmaker
        main_module.seed_if_empty = original_seed_if_empty

    assert calls == ["migrate", "sessionmaker", "seed"]
    print("PASS: startup init uses migration runner before seed")


if __name__ == "__main__":
    main()
