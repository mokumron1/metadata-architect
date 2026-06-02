"""
Abstract notification adapter interface.

All adapters (SendGrid, Slack) implement NotificationAdapter.
The dispatcher selects active adapters from settings and calls
send() on each concurrently.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class NotificationType(str, Enum):
    VERIFICATION_PULSE = "verification_pulse"   # SME: please review this draft
    ORPHAN_NOTICE = "orphan_notice"             # SLA breached, asset orphaned
    REJECTION_NOTICE = "rejection_notice"       # SME rejected the asset
    APPROVAL_NOTICE = "approval_notice"         # SME approved, asset certified


@dataclass
class NotificationPayload:
    notification_type: NotificationType
    recipient_email: str
    asset_id: str
    asset_name: str
    workflow_id: str
    # Type-specific fields
    review_link: str | None = None          # VERIFICATION_PULSE
    sla_deadline_iso: str | None = None     # VERIFICATION_PULSE, ORPHAN_NOTICE
    tdk_score: float | None = None          # all types
    sme_name: str | None = None
    extra: dict = field(default_factory=dict)


class NotificationAdapter(ABC):
    """Base class for all notification channel adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel identifier for logging."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required credentials are present in settings."""

    @abstractmethod
    async def send(self, payload: NotificationPayload) -> bool:
        """
        Send the notification. Returns True on success, False on failure.
        Must never raise — log and return False instead.
        """
