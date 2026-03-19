from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ValidationStatus(str, Enum):
    VALID = "VALID"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HARD_BLOCK = "hard_block"


class ConflictType(str, Enum):
    PRAYER = "prayer"
    SLEEP = "sleep"
    SECOND_SLEEP = "second_sleep"
    FAMILY = "family"
    SIYAM_DAYTIME_LOAD = "siyam_daytime_load"


@dataclass
class ValidationResult:
    status: ValidationStatus
    severity: ValidationSeverity = ValidationSeverity.INFO
    reason_code: Optional[str] = None
    message: Optional[str] = None

    conflict_type: Optional[ConflictType] = None
    conflict_start: Optional[datetime] = None
    conflict_end: Optional[datetime] = None

    recommended_action: Optional[str] = None
    suggested_slot_start: Optional[datetime] = None
    suggested_slot_end: Optional[datetime] = None

    def is_valid(self) -> bool:
        return self.status == ValidationStatus.VALID

    def has_conflict(self) -> bool:
        return self.status == ValidationStatus.CONFLICT

    def is_warning(self) -> bool:
        return self.severity == ValidationSeverity.WARNING

    def is_hard_block(self) -> bool:
        return self.severity == ValidationSeverity.HARD_BLOCK
