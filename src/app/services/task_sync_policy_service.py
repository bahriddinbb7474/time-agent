from __future__ import annotations

from dataclasses import dataclass


SYNC_TO_GOOGLE = "sync_to_google"
LOCAL_ONLY = "local_only"
LOCAL_ONLY_RESTRICTED = "local_only_restricted"

SKIP_REASON_CATEGORY_POLICY = "category_policy"
SKIP_REASON_RESTRICTED_CONTENT = "restricted_content"

KNOWN_CATEGORIES = {
    "work",
    "family",
    "health",
    "prayer",
    "personal",
    "other",
}


@dataclass(frozen=True)
class TaskSyncPolicyDecisionDTO:
    category: str
    policy: str
    sync_allowed: bool
    sync_status_if_skipped: str | None
    skip_reason: str | None
    user_message_template: str | None


class TaskSyncPolicyService:
    def normalize_category(self, category: str | None) -> str:
        raw = (category or "").strip().lower()

        if raw in KNOWN_CATEGORIES:
            return raw

        return "other"

    def decide(self, category: str | None) -> TaskSyncPolicyDecisionDTO:
        normalized = self.normalize_category(category)

        if normalized == "work":
            return TaskSyncPolicyDecisionDTO(
                category="work",
                policy=SYNC_TO_GOOGLE,
                sync_allowed=True,
                sync_status_if_skipped=None,
                skip_reason=None,
                user_message_template=None,
            )

        if normalized == "family":
            return TaskSyncPolicyDecisionDTO(
                category="family",
                policy=LOCAL_ONLY,
                sync_allowed=False,
                sync_status_if_skipped="skipped_by_policy",
                skip_reason=SKIP_REASON_CATEGORY_POLICY,
                user_message_template=(
                    "✅ Запись сохранена локально. "
                    "Личные и семейные дела защищены от внешней синхронизации."
                ),
            )

        if normalized == "health":
            return TaskSyncPolicyDecisionDTO(
                category="health",
                policy=LOCAL_ONLY,
                sync_allowed=False,
                sync_status_if_skipped="skipped_by_policy",
                skip_reason=SKIP_REASON_CATEGORY_POLICY,
                user_message_template=(
                    "✅ Запись сохранена локально. "
                    "Задачи здоровья остаются внутри вашего личного контура."
                ),
            )

        if normalized == "prayer":
            return TaskSyncPolicyDecisionDTO(
                category="prayer",
                policy=LOCAL_ONLY_RESTRICTED,
                sync_allowed=False,
                sync_status_if_skipped="skipped_by_policy",
                skip_reason=SKIP_REASON_RESTRICTED_CONTENT,
                user_message_template=(
                    "✅ Запись сохранена локально. "
                    "Ваши духовные приоритеты защищены от внешней синхронизации."
                ),
            )

        if normalized == "personal":
            return TaskSyncPolicyDecisionDTO(
                category="personal",
                policy=LOCAL_ONLY,
                sync_allowed=False,
                sync_status_if_skipped="skipped_by_policy",
                skip_reason=SKIP_REASON_CATEGORY_POLICY,
                user_message_template=(
                    "✅ Запись сохранена локально. "
                    "Личные задачи остаются внутри вашего личного контура."
                ),
            )

        return TaskSyncPolicyDecisionDTO(
            category="other",
            policy=LOCAL_ONLY,
            sync_allowed=False,
            sync_status_if_skipped="skipped_by_policy",
            skip_reason=SKIP_REASON_CATEGORY_POLICY,
            user_message_template=(
                "✅ Запись сохранена локально. "
                "Неопределённые и личные задачи по умолчанию "
                "не отправляются во внешний календарь."
            ),
        )
