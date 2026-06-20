from __future__ import annotations

from dataclasses import dataclass

KNOWN_CATEGORIES = {
    "work",
    "family",
    "health",
    "prayer",
    "personal",
    "other",
}


@dataclass(frozen=True)
class TimeGroup:
    code: str
    label: str
    description: str


TIME_GROUPS: tuple[TimeGroup, ...] = (
    TimeGroup("sleep", "Сон", "Сон и восстановление"),
    TimeGroup("prayer", "Намаз", "Обязательные и дополнительные молитвы"),
    TimeGroup("quran", "Коран", "Чтение и изучение Корана"),
    TimeGroup(
        "hadith_religious",
        "Хадис / религиозное чтение",
        "Хадисы и религиозная литература",
    ),
    TimeGroup("dhikr", "Зикр", "Зикр и духовные практики"),
    TimeGroup("food", "Питание", "Приёмы пищи и приготовление еды"),
    TimeGroup("hygiene", "Гигиена", "Личная гигиена и уход"),
    TimeGroup("study", "Учёба", "Обучение и развитие навыков"),
    TimeGroup(
        "ai_projects",
        "ИИ-кодинг / проекты",
        "Разработка и реализация проектов с ИИ",
    ),
    TimeGroup("sport", "Спорт", "Спорт и физическая активность"),
    TimeGroup("youtube_news", "YouTube / новости", "Просмотр YouTube и новостей"),
    TimeGroup("road", "Дорога", "Поездки и перемещения"),
    TimeGroup("work", "Работа", "Рабочие задачи"),
    TimeGroup("children_study", "Учёба детей", "Обучение и занятия с детьми"),
    TimeGroup("family_time", "Семья", "Семейные дела и совместное время"),
    TimeGroup("relationships", "Близкие / друзья", "Общение с близкими и друзьями"),
    TimeGroup("entertainment", "Развлечение", "Отдых и развлечения"),
    TimeGroup("no_data", "Не определено", "Время без подтверждённых данных"),
    TimeGroup(
        "waste",
        "Впустую",
        "Время, явно отмеченное владельцем как потерянное",
    ),
)

TIME_GROUP_CODES = frozenset(group.code for group in TIME_GROUPS)


def normalize_time_group(code: str | None) -> str:
    normalized = (code or "").strip().lower()
    return normalized if normalized in TIME_GROUP_CODES else "no_data"
