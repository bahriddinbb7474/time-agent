from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    days_of_week: Mapped[str] = mapped_column(String(32), nullable=False, default="*")
    policy: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="never_move",
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_context_status", "context_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)

    planned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="todo")

    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="personal",
    )

    context_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="normal",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

class CrisisStack(Base):
    __tablename__ = "crisis_stacks"
    __table_args__ = (
        Index("ix_crisis_stacks_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    tasks: Mapped[list["CrisisStackTask"]] = relationship(
        "CrisisStackTask",
        back_populates="stack",
        cascade="all, delete-orphan",
        order_by="CrisisStackTask.priority_position",
    )


class CrisisStackTask(Base):
    __tablename__ = "crisis_stack_tasks"
    __table_args__ = (
        UniqueConstraint("stack_id", "task_id", name="uq_crisis_stack_tasks_stack_task"),
        UniqueConstraint(
            "stack_id",
            "priority_position",
            name="uq_crisis_stack_tasks_stack_priority",
        ),
        Index("ix_crisis_stack_tasks_stack_priority", "stack_id", "priority_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    stack_id: Mapped[int] = mapped_column(
        ForeignKey("crisis_stacks.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority_position: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    stack: Mapped["CrisisStack"] = relationship("CrisisStack", back_populates="tasks")

class TaskExternalLink(Base):
    __tablename__ = "task_external_links"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "provider",
            name="uq_task_external_links_task_provider",
        ),
        Index("ix_task_external_links_sync_status", "sync_status"),
        Index("ix_task_external_links_external_id", "external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False)

    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    external_calendar_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    sync_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="sync_pending",
    )

    skip_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    state: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        unique=True,
        index=True,
    )

    code_verifier: Mapped[str] = mapped_column(String(512), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UserRoutine(Base):
    __tablename__ = "user_routines"
    __table_args__ = (
        UniqueConstraint("mode", name="uq_user_routines_mode"),
        Index("ix_user_routines_mode", "mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    mode: Mapped[str] = mapped_column(String(16), nullable=False)

    sleep_start: Mapped[time] = mapped_column(Time, nullable=False)
    sleep_end: Mapped[time] = mapped_column(Time, nullable=False)

    second_sleep_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    second_sleep_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PrayerTime(Base):
    __tablename__ = "prayer_times"
    __table_args__ = (
        UniqueConstraint("date", name="uq_prayer_times_date"),
        Index("ix_prayer_times_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    date: Mapped[date] = mapped_column(Date, nullable=False)

    fajr: Mapped[time] = mapped_column(Time, nullable=False)
    dhuhr: Mapped[time] = mapped_column(Time, nullable=False)
    asr: Mapped[time] = mapped_column(Time, nullable=False)
    maghrib: Mapped[time] = mapped_column(Time, nullable=False)
    isha: Mapped[time] = mapped_column(Time, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class AlertQueue(Base):
    __tablename__ = "alert_queue"
    __table_args__ = (
        Index("ix_alert_queue_status", "status"),
        Index("ix_alert_queue_scheduled_for", "scheduled_for"),
        Index("ix_alert_queue_priority", "priority"),
        Index("ix_alert_queue_type_status", "alert_type", "status"),
        Index("ix_alert_queue_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    repeat_interval_min: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
    )

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class QuranProgressEntry(Base):
    __tablename__ = "quran_progress"
    __table_args__ = (
        Index("ix_quran_progress_created_at", "created_at"),
        Index("ix_quran_progress_page", "page"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    surah: Mapped[str] = mapped_column(String(128), nullable=False)
    ayah: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class RelativesContactRule(Base):
    __tablename__ = "relatives_contact_rules"
    __table_args__ = (
        Index("ix_relatives_contact_rules_category", "category"),
        Index("ix_relatives_contact_rules_contact_type", "contact_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(1), nullable=False)
    min_contact_frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    contact_type: Mapped[str] = mapped_column(String(16), nullable=False)

    last_contact_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class DailyHealthContext(Base):
    __tablename__ = "daily_health_contexts"
    __table_args__ = (
        UniqueConstraint("date", name="uq_daily_health_contexts_date"),
        Index("ix_daily_health_contexts_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    date: Mapped[date] = mapped_column(Date, nullable=False)

    is_siyam_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    siyam_state_source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="heuristic",
    )
    hydration_daylight_suppressed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    low_energy_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


Index("ix_oauth_states_user_state", OAuthState.user_id, OAuthState.state)


