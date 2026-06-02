"""
Slack adapter — posts to a governance channel via Incoming Webhooks.

Uses the Slack Block Kit format for rich, actionable messages.
Gracefully no-ops when SLACK_BOT_TOKEN is not configured.
"""

import logging

import httpx

from metadata_architect.config import get_settings
from metadata_architect.notifications.base import (
    NotificationAdapter,
    NotificationPayload,
    NotificationType,
)

log = logging.getLogger(__name__)

_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"

# Emoji per notification type
_EMOJI = {
    NotificationType.VERIFICATION_PULSE: ":mag:",
    NotificationType.ORPHAN_NOTICE: ":warning:",
    NotificationType.REJECTION_NOTICE: ":x:",
    NotificationType.APPROVAL_NOTICE: ":white_check_mark:",
}


class SlackAdapter(NotificationAdapter):
    @property
    def name(self) -> str:
        return "slack"

    def is_configured(self) -> bool:
        return bool(get_settings().slack_bot_token)

    async def send(self, payload: NotificationPayload) -> bool:
        if not self.is_configured():
            log.warning("slack.not_configured — skipping Slack notification")
            return False
        try:
            settings = get_settings()
            blocks = _build_blocks(payload)
            body = {
                "channel": settings.slack_governance_channel,
                "text": _fallback_text(payload),
                "blocks": blocks,
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    _SLACK_POST_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                )
            data = resp.json()
            if data.get("ok"):
                log.info("slack.sent", extra={
                    "type": payload.notification_type,
                    "channel": settings.slack_governance_channel,
                    "asset": payload.asset_name,
                })
                return True
            log.error("slack.failed", extra={"error": data.get("error")})
            return False
        except Exception as exc:
            log.error("slack.exception", extra={"error": str(exc)})
            return False


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------

def _fallback_text(p: NotificationPayload) -> str:
    emoji = _EMOJI.get(p.notification_type, ":bell:")
    return f"{emoji} Metadata Architect: {p.notification_type.value} for *{p.asset_name}*"


def _build_blocks(p: NotificationPayload) -> list[dict]:
    emoji = _EMOJI.get(p.notification_type, ":bell:")

    header_text = {
        NotificationType.VERIFICATION_PULSE: f"{emoji} *Review Required:* `{p.asset_name}`",
        NotificationType.ORPHAN_NOTICE: f"{emoji} *Asset Orphaned — SLA Breached:* `{p.asset_name}`",
        NotificationType.REJECTION_NOTICE: f"{emoji} *Metadata Rejected:* `{p.asset_name}`",
        NotificationType.APPROVAL_NOTICE: f"{emoji} *Asset Certified:* `{p.asset_name}`",
    }.get(p.notification_type, f"{emoji} *{p.notification_type}:* `{p.asset_name}`")

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Asset ID:*\n`{p.asset_id}`"},
                {"type": "mrkdwn", "text": f"*Workflow:*\n`{p.workflow_id}`"},
            ],
        },
    ]

    if p.tdk_score is not None:
        score_bar = _score_bar(p.tdk_score)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*TDK Score:* {score_bar} `{p.tdk_score:.2f}`"},
        })

    if p.sla_deadline_iso:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*SLA Deadline:* {p.sla_deadline_iso}"},
        })

    if p.review_link:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Review in Portal"},
                    "url": p.review_link,
                    "style": "primary",
                }
            ],
        })

    blocks.append({"type": "divider"})
    return blocks


def _score_bar(score: float) -> str:
    filled = round(score * 10)
    return "█" * filled + "░" * (10 - filled)
