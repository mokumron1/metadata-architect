"""
SendGrid email adapter for the Verification Pulse and Orphan Notice.

Sends HTML emails with action buttons linking to the SME Review Portal.
Gracefully no-ops when SENDGRID_API_KEY is not configured.
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

_SENDGRID_SEND_URL = "https://api.sendgrid.com/v3/mail/send"
_FROM_EMAIL = "no-reply@metadata-architect.ai"
_FROM_NAME = "Metadata Architect"


class SendGridAdapter(NotificationAdapter):
    @property
    def name(self) -> str:
        return "sendgrid"

    def is_configured(self) -> bool:
        return bool(get_settings().sendgrid_api_key)

    async def send(self, payload: NotificationPayload) -> bool:
        if not self.is_configured():
            log.warning("sendgrid.not_configured — skipping email notification")
            return False
        try:
            html = _render_html(payload)
            subject = _subject(payload)
            body = {
                "personalizations": [
                    {"to": [{"email": payload.recipient_email}]}
                ],
                "from": {"email": _FROM_EMAIL, "name": _FROM_NAME},
                "subject": subject,
                "content": [{"type": "text/html", "value": html}],
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    _SENDGRID_SEND_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {get_settings().sendgrid_api_key}"},
                )
            if resp.status_code in (200, 202):
                log.info("sendgrid.sent", extra={
                    "type": payload.notification_type,
                    "recipient": payload.recipient_email,
                    "asset": payload.asset_name,
                })
                return True
            log.error("sendgrid.failed", extra={"status": resp.status_code, "body": resp.text[:200]})
            return False
        except Exception as exc:
            log.error("sendgrid.exception", extra={"error": str(exc)})
            return False


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def _subject(payload: NotificationPayload) -> str:
    subjects = {
        NotificationType.VERIFICATION_PULSE: f"[Action Required] Review metadata draft: {payload.asset_name}",
        NotificationType.ORPHAN_NOTICE: f"[Urgent] Data asset orphaned — SLA breached: {payload.asset_name}",
        NotificationType.REJECTION_NOTICE: f"[Notice] Metadata rejected: {payload.asset_name}",
        NotificationType.APPROVAL_NOTICE: f"[Certified] Metadata approved: {payload.asset_name}",
    }
    return subjects.get(payload.notification_type, f"Metadata Architect: {payload.asset_name}")


def _render_html(payload: NotificationPayload) -> str:
    if payload.notification_type == NotificationType.VERIFICATION_PULSE:
        return _verification_pulse_html(payload)
    if payload.notification_type == NotificationType.ORPHAN_NOTICE:
        return _orphan_notice_html(payload)
    return _generic_html(payload)


def _verification_pulse_html(p: NotificationPayload) -> str:
    btn = (
        f'<a href="{p.review_link}" style="background:#2563eb;color:white;'
        f'padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">'
        f'Review &amp; Certify</a>'
    ) if p.review_link else ""
    deadline = f"<p><strong>SLA Deadline:</strong> {p.sla_deadline_iso}</p>" if p.sla_deadline_iso else ""
    score = f"<p><strong>Initial TDK Score:</strong> {p.tdk_score:.2f}</p>" if p.tdk_score else ""
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <h2 style="color:#1e3a5f;">Metadata Review Required</h2>
      <p>A Statement of Intent has been drafted for the following data asset.
         Your review is required to certify it for downstream use.</p>
      <table style="border-collapse:collapse;width:100%;margin:16px 0;">
        <tr><td style="padding:8px;background:#f3f4f6;"><strong>Asset</strong></td>
            <td style="padding:8px;">{p.asset_name}</td></tr>
        <tr><td style="padding:8px;background:#f3f4f6;"><strong>Asset ID</strong></td>
            <td style="padding:8px;">{p.asset_id}</td></tr>
      </table>
      {score}{deadline}
      <p style="margin-top:24px;">{btn}</p>
      <hr style="margin-top:40px;border:none;border-top:1px solid #e5e7eb;"/>
      <p style="color:#6b7280;font-size:12px;">
        Sent by Metadata Architect &bull; This link expires at your SLA deadline.
      </p>
    </div>
    """


def _orphan_notice_html(p: NotificationPayload) -> str:
    score = f"<p><strong>Degraded TDK Score:</strong> {p.tdk_score:.2f}</p>" if p.tdk_score else ""
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <h2 style="color:#dc2626;">Data Asset Orphaned — SLA Breached</h2>
      <p>The review SLA for the following asset has expired without SME action.
         The asset has been orphaned and downstream access has been restricted.</p>
      <table style="border-collapse:collapse;width:100%;margin:16px 0;">
        <tr><td style="padding:8px;background:#fef2f2;"><strong>Asset</strong></td>
            <td style="padding:8px;">{p.asset_name}</td></tr>
        <tr><td style="padding:8px;background:#fef2f2;"><strong>Asset ID</strong></td>
            <td style="padding:8px;">{p.asset_id}</td></tr>
      </table>
      {score}
      <p>Please log in to the Metadata Architect portal to recertify this asset.</p>
      <hr style="margin-top:40px;border:none;border-top:1px solid #e5e7eb;"/>
      <p style="color:#6b7280;font-size:12px;">Sent by Metadata Architect</p>
    </div>
    """


def _generic_html(p: NotificationPayload) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <h2>Metadata Architect Notification</h2>
      <p>Asset: <strong>{p.asset_name}</strong> ({p.asset_id})</p>
      <p>Type: {p.notification_type}</p>
    </div>
    """
