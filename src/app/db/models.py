from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
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


    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DailyPlan(Base):
    __tablename__ = "daily_plans"
    __table_args__ = (
        UniqueConstraint("plan_date", name="uq_daily_plans_plan_date"),
        Index("ix_daily_plans_plan_date", "plan_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="telegram_manual",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class CaptureDraftRecord(Base):
    __tablename__ = "capture_drafts"
    __table_args__ = (
        Index(
            "ix_capture_drafts_user_status_created",
            "telegram_chat_id",
            "telegram_user_id",
            "status",
            "created_at",
        ),
        Index("ix_capture_drafts_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_type: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
    )

    advisor_proposal_json: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class ApiUsageRecord(Base):
    __tablename__ = "api_usage"
    __table_args__ = (
        Index("ix_api_usage_date_service", "usage_date", "service_type"),
        Index("ix_api_usage_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    audio_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="success")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DailyTargetDefinition(Base):
    __tablename__ = "daily_target_definitions"
    __table_args__ = (
        Index("ix_daily_target_definitions_active", "active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    target_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="minimum")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    weekdays_mask: Mapped[int] = mapped_column(Integer, nullable=False, default=127)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    progress_entries: Mapped[list["DailyTargetProgress"]] = relationship(
        "DailyTargetProgress",
        back_populates="target",
        cascade="all, delete-orphan",
    )


class DailyTargetProgress(Base):
    __tablename__ = "daily_target_progress"
    __table_args__ = (
        UniqueConstraint(
            "target_id",
            "usage_date",
            name="uq_daily_target_progress_target_date",
        ),
        Index("ix_daily_target_progress_usage_date", "usage_date"),
        Index("ix_daily_target_progress_target_id", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("daily_target_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_value_snapshot: Mapped[float] = mapped_column(Float, nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    target: Mapped["DailyTargetDefinition"] = relationship(
        "DailyTargetDefinition",
        back_populates="progress_entries",
    )


class DailySchedule(Base):
    __tablename__ = "daily_schedules"
    __table_args__ = (
        UniqueConstraint("user_id", "usage_date", name="uq_daily_schedules_user_date"),
        Index("ix_daily_schedules_user_date", "user_id", "usage_date"),
        Index("ix_daily_schedules_status", "status"),
        CheckConstraint("version >= 1", name="ck_daily_schedules_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    time_blocks: Mapped[list["TimeBlock"]] = relationship(
        "TimeBlock",
        back_populates="schedule",
        cascade="all, delete-orphan",
    )


class TimeBlock(Base):
    __tablename__ = "time_blocks"
    __table_args__ = (
        Index("ix_time_blocks_schedule_start", "schedule_id", "start_at"),
        Index("ix_time_blocks_user_start", "user_id", "start_at"),
        CheckConstraint("end_at > start_at", name="ck_time_blocks_valid_interval"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("daily_schedules.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    flexibility: Mapped[str] = mapped_column(String(16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    schedule: Mapped["DailySchedule"] = relationship(
        "DailySchedule", back_populates="time_blocks"
    )


class ActivityEntry(Base):
    __tablename__ = "activity_entries"
    __table_args__ = (
        Index("ix_activity_entries_user_date", "user_id", "usage_date"),
        Index("ix_activity_entries_user_start", "user_id", "start_at"),
        CheckConstraint("end_at > start_at", name="ck_activity_entries_valid_interval"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_activity_entries_confidence_range",
        ),
        CheckConstraint(
            "waste_marked_by_owner = 0 OR owner_confirmed = 1",
            name="ck_activity_entries_waste_owner_confirmed",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    waste_marked_by_owner: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Checkin(Base):
    __tablename__ = "checkins"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "window_start", "window_end", name="uq_checkins_user_window"
        ),
        Index("ix_checkins_user_window", "user_id", "window_start"),
        Index("ix_checkins_user_status", "user_id", "status"),
        Index("ix_checkins_schedule_version", "schedule_id", "schedule_version"),
        Index("ix_checkins_user_date", "user_id", "usage_date"),
        CheckConstraint("window_end > window_start", name="ck_checkins_valid_window"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schedule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prompted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    response_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
