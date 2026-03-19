from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db import crud


@dataclass(slots=True)
class QuranProgressDTO:
    id: int
    surah: str
    ayah: int
    page: int
    created_at: datetime


@dataclass(slots=True)
class QuranDailySummary:
    last_entry: QuranProgressDTO | None
    previous_entry: QuranProgressDTO | None
    pages_read_today: int
    remaining_goal: int
    goal_reached: bool


class QuranParseError(Exception):
    pass


class QuranConfirmationRequired(QuranParseError):
    def __init__(self, message: str, *, previous_page: int, new_page: int) -> None:
        super().__init__(message)
        self.previous_page = previous_page
        self.new_page = new_page


class QuranService:
    """
    Quran progress tracker with fool-protection.

    Input format:
    [Сура] [Аят] [Лист]

    Example:
    Бакара 270 46
    """

    MAX_PAGE = 604
    DAILY_GOAL = 20

    SURAH_ALIASES = {
        # 1. Аль-Фатиха
        "фатиха": "Фатиха",
        "алфатиха": "Фатиха",
        "альфатиха": "Фатиха",
        "fatiha": "Фатиха",
        "alfatiha": "Фатиха",
        "fatikha": "Фатиха",
        # 2. Аль-Бакара
        "бакара": "Бакара",
        "альбакара": "Бакара",
        "албакара": "Бакара",
        "баккара": "Бакара",
        "baqara": "Бакара",
        "bakara": "Бакара",
        "albaqara": "Бакара",
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    def parse_input(self, text: str) -> tuple[str, int, int]:
        if not text or not text.strip():
            raise QuranParseError("Пустой ввод.")

        parts = text.strip().split()
        if len(parts) != 3:
            raise QuranParseError(
                "Формат должен быть: Сура Аят Лист\nПример: Бакара 270 46"
            )

        surah_raw, ayah_raw, page_raw = parts
        surah = self._normalize_surah(surah_raw)

        if not ayah_raw.isdigit():
            raise QuranParseError("Номер аята должен быть числом.")

        if not page_raw.isdigit():
            raise QuranParseError("Номер листа должен быть числом.")

        ayah = int(ayah_raw)
        page = int(page_raw)

        if ayah <= 0:
            raise QuranParseError("Номер аята должен быть больше нуля.")

        if page < 1 or page > self.MAX_PAGE:
            raise QuranParseError("Лист должен быть в диапазоне 1..604.")

        return surah, ayah, page

    async def save_progress_from_text(
        self,
        text: str,
        *,
        allow_backward: bool = False,
    ) -> QuranProgressDTO:
        surah, ayah, page = self.parse_input(text)

        latest = await crud.get_latest_quran_progress(self.session)
        previous_page = latest.page if latest is not None else None

        self._validate_progress(
            new_page=page,
            previous_page=previous_page,
            allow_backward=allow_backward,
        )

        entry = await crud.add_quran_progress(
            self.session,
            surah=surah,
            ayah=ayah,
            page=page,
        )

        return self._to_dto(entry)

    async def needs_backward_confirmation(self, text: str) -> bool:
        _, _, page = self.parse_input(text)

        latest = await crud.get_latest_quran_progress(self.session)
        previous_page = latest.page if latest is not None else None

        if previous_page is None:
            return False

        return page < previous_page

    async def get_latest_progress(self) -> QuranProgressDTO | None:
        entry = await crud.get_latest_quran_progress(self.session)
        if entry is None:
            return None
        return self._to_dto(entry)

    async def get_daily_summary(
        self,
        *,
        reference_dt: datetime | None = None,
    ) -> QuranDailySummary:
        ref = reference_dt.astimezone(APP_TZ) if reference_dt else now_tz()

        day_start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        entries_today = await crud.list_quran_progress_for_day(
            self.session,
            day_start=day_start,
            day_end=day_end,
        )

        if not entries_today:
            previous = await crud.get_latest_quran_progress_before(
                self.session,
                before_dt=day_start,
            )
            return QuranDailySummary(
                last_entry=None,
                previous_entry=self._to_dto(previous) if previous else None,
                pages_read_today=0,
                remaining_goal=self.DAILY_GOAL,
                goal_reached=False,
            )

        previous = await crud.get_latest_quran_progress_before(
            self.session,
            before_dt=day_start,
        )

        previous_page = previous.page if previous is not None else None
        pages_read_today = self._calculate_daily_unique_progress(
            previous_page=previous_page,
            entries_today=entries_today,
        )
        remaining_goal = self._calculate_remaining_goal(
            pages_read_today=pages_read_today
        )

        last_today = entries_today[-1]

        return QuranDailySummary(
            last_entry=self._to_dto(last_today),
            previous_entry=self._to_dto(previous) if previous else None,
            pages_read_today=pages_read_today,
            remaining_goal=remaining_goal,
            goal_reached=remaining_goal == 0,
        )

    def build_deficit_message(self, summary: QuranDailySummary) -> str:
        if summary.goal_reached:
            return (
                "📖 Коран\n"
                f"Сегодня новый прогресс: {summary.pages_read_today} стр.\n"
                "Дневная цель выполнена ✅"
            )

        if summary.last_entry is None:
            return (
                "📖 Коран\n"
                "Сегодня прогресс ещё не отмечен.\n"
                f"До дневной цели осталось: {summary.remaining_goal} стр."
            )

        return (
            "📖 Коран\n"
            f"Последняя отметка: {summary.last_entry.surah} "
            f"{summary.last_entry.ayah}, стр. {summary.last_entry.page}\n"
            f"Сегодня новый прогресс: {summary.pages_read_today} стр.\n"
            f"До дневной цели осталось: {summary.remaining_goal} стр."
        )

    def _validate_progress(
        self,
        *,
        new_page: int,
        previous_page: int | None,
        allow_backward: bool,
    ) -> None:
        if previous_page is None:
            return

        if new_page < previous_page and not allow_backward:
            raise QuranConfirmationRequired(
                "Вы указали страницу раньше предыдущей.\nПродолжить?",
                previous_page=previous_page,
                new_page=new_page,
            )

    def _calculate_daily_unique_progress(
        self,
        *,
        previous_page: int | None,
        entries_today: list,
    ) -> int:
        if not entries_today:
            return 0

        baseline = previous_page if previous_page is not None else entries_today[0].page
        max_page_seen = baseline
        pages_progress = 0

        for entry in entries_today:
            if entry.page > max_page_seen:
                pages_progress += entry.page - max_page_seen
                max_page_seen = entry.page

        return max(0, pages_progress)

    def _calculate_remaining_goal(
        self,
        *,
        pages_read_today: int,
    ) -> int:
        remaining = self.DAILY_GOAL - pages_read_today
        return max(0, remaining)

    def _normalize_surah(self, name: str) -> str:
        normalized = (
            name.lower()
            .strip()
            .replace(" ", "")
            .replace("-", "")
            .replace("’", "")
            .replace("'", "")
            .replace("`", "")
        )

        surah = self.SURAH_ALIASES.get(normalized)
        if surah is not None:
            return surah

        allowed_examples = "Фатиха, Бакара"
        raise QuranParseError(
            "Сура не распознана уверенно.\n"
            f"Пожалуйста, уточните название. Примеры: {allowed_examples}"
        )

    @staticmethod
    def _to_dto(entry) -> QuranProgressDTO:
        return QuranProgressDTO(
            id=entry.id,
            surah=entry.surah,
            ayah=entry.ayah,
            page=entry.page,
            created_at=entry.created_at.astimezone(APP_TZ),
        )
