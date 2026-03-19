from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession


from app.services.rules_service import RulesService

router = Router()


@router.message(Command("rules"))
async def rules_cmd(message: Message, session: AsyncSession) -> None:
    service = RulesService(session)
    rules = await service.list_rules()

    if not rules:
        await message.answer("Пока нет правил.")
        return

    lines = ["🛡️ Защищённые слоты:\n"]
    for r in rules:
        days = "ежедневно" if r.days_of_week == "*" else r.days_of_week
        lines.append(f"• {r.name}: {r.start_time}-{r.end_time} ({days}) — {r.policy}")

    await message.answer("\n".join(lines))
