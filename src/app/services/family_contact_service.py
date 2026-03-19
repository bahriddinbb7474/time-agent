from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db.models import RelativesContactRule


@dataclass(slots=True)
class FamilyCategorySemantics:
    category: str
    meaning: str
    priority_rank: int


@dataclass(slots=True)
class FamilyContactRuleDTO:
    id: int
    name: str
    category: str
    min_contact_frequency: int
    contact_type: str
    last_contact_at: datetime | None


@dataclass(slots=True)
class FamilyApproachingDueContact:
    rule_id: int
    name: str
    category: str
    category_meaning: str
    category_priority_rank: int
    contact_type: str
    due_at: datetime
    days_until_due: int


@dataclass(slots=True)
class FamilyReminderCandidate:
    rule_id: int
    title: str
    category: str
    category_meaning: str
    category_priority_rank: int
    contact_type: str
    due_at: datetime


class FamilyContactService:
    """
    Foundation skeleton for family contact reminders.

    Scope for this step:
    - read contact rules
    - compute approaching due contacts
    - generate reminder candidates
    """

    DEFAULT_LOOKAHEAD_DAYS = 3
    CATEGORY_SEMANTICS: dict[str, FamilyCategorySemantics] = {
        "A": FamilyCategorySemantics(
            category="A",
            meaning="highest_relational_priority",
            priority_rank=0,
        ),
        "B": FamilyCategorySemantics(
            category="B",
            meaning="obligation_tracking",
            priority_rank=1,
        ),
        "C": FamilyCategorySemantics(
            category="C",
            meaning="softer_maintenance",
            priority_rank=2,
        ),
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_contact_rules(self) -> list[FamilyContactRuleDTO]:
        stmt = select(RelativesContactRule).order_by(RelativesContactRule.id.asc())
        result = await self.session.execute(stmt)
        rules = result.scalars().all()
        return [self._to_rule_dto(rule) for rule in rules]

    async def get_approaching_due_contacts(
        self,
        *,
        reference_dt: datetime | None = None,
        lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
    ) -> list[FamilyApproachingDueContact]:
        now_local = self._ensure_app_tz(reference_dt or now_tz())
        window_end_date = now_local.date() + timedelta(days=max(0, lookahead_days))

        rules = await self.list_contact_rules()
        approaching: list[FamilyApproachingDueContact] = []

        for rule in rules:
            due_at = self._compute_due_at(rule=rule, reference_dt=now_local)
            if due_at.date() > window_end_date:
                continue

            semantics = self._resolve_category_semantics(rule.category)
            delta_days = (due_at.date() - now_local.date()).days
            approaching.append(
                FamilyApproachingDueContact(
                    rule_id=rule.id,
                    name=rule.name,
                    category=rule.category,
                    category_meaning=semantics.meaning,
                    category_priority_rank=semantics.priority_rank,
                    contact_type=rule.contact_type,
                    due_at=due_at,
                    days_until_due=delta_days,
                )
            )

        # Foundation ordering only: earliest due first; within same due time A -> B -> C.
        approaching.sort(
            key=lambda item: (
                item.due_at,
                item.category_priority_rank,
                item.rule_id,
            )
        )
        return approaching

    async def build_reminder_candidates(
        self,
        *,
        reference_dt: datetime | None = None,
        lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
    ) -> list[FamilyReminderCandidate]:
        due_contacts = await self.get_approaching_due_contacts(
            reference_dt=reference_dt,
            lookahead_days=lookahead_days,
        )

        candidates: list[FamilyReminderCandidate] = []
        for item in due_contacts:
            title = self._build_candidate_title(
                name=item.name,
                contact_type=item.contact_type,
            )
            candidates.append(
                FamilyReminderCandidate(
                    rule_id=item.rule_id,
                    title=title,
                    category=item.category,
                    category_meaning=item.category_meaning,
                    category_priority_rank=item.category_priority_rank,
                    contact_type=item.contact_type,
                    due_at=item.due_at,
                )
            )

        return candidates

    async def build_today_reminder_candidates(
        self,
        *,
        existing_task_titles: list[str] | None = None,
        reference_dt: datetime | None = None,
    ) -> list[FamilyReminderCandidate]:
        raw_candidates = await self.build_reminder_candidates(
            reference_dt=reference_dt,
            lookahead_days=0,
        )

        now_local = self._ensure_app_tz(reference_dt or now_tz())
        existing_keys = {
            self._normalize_title_key(title)
            for title in (existing_task_titles or [])
            if title
        }

        seen_keys: set[str] = set()
        result: list[FamilyReminderCandidate] = []

        for candidate in raw_candidates:
            if candidate.due_at.date() > now_local.date():
                continue

            key = self._normalize_title_key(candidate.title)
            if key in existing_keys:
                continue
            if key in seen_keys:
                continue

            seen_keys.add(key)
            result.append(candidate)

        return result

    def _compute_due_at(
        self,
        *,
        rule: FamilyContactRuleDTO,
        reference_dt: datetime,
    ) -> datetime:
        min_days = max(0, int(rule.min_contact_frequency))

        if rule.last_contact_at is None:
            return reference_dt

        base = self._ensure_app_tz(rule.last_contact_at)
        return base + timedelta(days=min_days)

    @classmethod
    def _resolve_category_semantics(cls, category: str | None) -> FamilyCategorySemantics:
        normalized = (category or "").strip().upper()
        return cls.CATEGORY_SEMANTICS.get(normalized, cls.CATEGORY_SEMANTICS["C"])

    @staticmethod
    def _build_candidate_title(*, name: str, contact_type: str) -> str:
        contact = (contact_type or "").strip().lower()

        if contact == "call":
            return f"Позвонить {name}"

        if contact == "visit":
            return f"Навестить {name}"

        if contact == "message":
            return f"Связаться с родственником {name}"

        return f"Связаться с {name}"

    @staticmethod
    def _normalize_title_key(title: str) -> str:
        return " ".join((title or "").strip().lower().split())

    @staticmethod
    def _to_rule_dto(rule: RelativesContactRule) -> FamilyContactRuleDTO:
        return FamilyContactRuleDTO(
            id=rule.id,
            name=rule.name,
            category=rule.category,
            min_contact_frequency=rule.min_contact_frequency,
            contact_type=rule.contact_type,
            last_contact_at=rule.last_contact_at,
        )

    @staticmethod
    def _ensure_app_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
