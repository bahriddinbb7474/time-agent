"""Local smoke test for /usage — run via codex_python.ps1."""
import asyncio
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.migration_runner import run_migrations
from app.db.models import ApiUsageRecord
from app.services.api_usage_service import ApiUsageService
from app.handlers.usage import _format_usage_message


async def main():
    tmp = tempfile.TemporaryDirectory(prefix="smoke_usage_")
    db_path = Path(tmp.name) / "smoke.db"
    run_migrations(db_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    today = date(2026, 6, 15)

    async with maker() as session:
        for secs, cost, st in [
            (4.7, 0.000098, "success"),
            (3.0, 0.000063, "success"),
            (6.5, 0.000137, "error"),
        ]:
            session.add(ApiUsageRecord(
                created_at=datetime.now(timezone.utc),
                usage_date=today,
                provider="openrouter",
                service_type="stt",
                model="openai/whisper-large-v3",
                request_count=1,
                audio_seconds=secs,
                estimated_cost_usd=cost,
                status=st,
                input_tokens=0,
                output_tokens=0,
            ))
        await session.commit()

    async with maker() as session:
        summary = await ApiUsageService(session).get_daily_summary(today)

    output = _format_usage_message(summary)
    await engine.dispose()
    tmp.cleanup()
    print("=== /usage smoke output ===")
    print(output)
    print("===========================")
    print("SMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
