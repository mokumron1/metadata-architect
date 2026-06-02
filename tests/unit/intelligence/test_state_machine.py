"""
Unit tests for the SmeWorkflow state machine.

Tests every valid transition, every invalid transition, and
the is_sla_breached property — all without touching the database.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from metadata_architect.models.asset_registry import (
    InvalidTransitionError,
    SmeWorkflow,
    WorkflowStatus,
    VALID_TRANSITIONS,
)


def _make_workflow(status: WorkflowStatus = WorkflowStatus.AWAITING_SME_AUDIT) -> SmeWorkflow:
    w = SmeWorkflow()
    w.id = uuid.uuid4()
    w.asset_id = uuid.uuid4()
    w.draft_id = uuid.uuid4()
    w.context_authority = "sme@example.com"
    w.status = status
    w.sla_breach_count = 0
    w.created_at = datetime.now(timezone.utc)
    return w


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

class TestValidTransitions:
    def test_awaiting_to_approved(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.SME_APPROVED, actioned_by="sme@example.com")
        assert w.status == WorkflowStatus.SME_APPROVED

    def test_awaiting_to_edited(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.SME_EDITED, actioned_by="sme@example.com")
        assert w.status == WorkflowStatus.SME_EDITED

    def test_awaiting_to_rejected(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.SME_REJECTED, actioned_by="sme@example.com")
        assert w.status == WorkflowStatus.SME_REJECTED

    def test_awaiting_to_orphaned(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.ORPHANED)
        assert w.status == WorkflowStatus.ORPHANED

    def test_edited_to_approved(self):
        w = _make_workflow(WorkflowStatus.SME_EDITED)
        w.transition(WorkflowStatus.SME_APPROVED, actioned_by="sme@example.com")
        assert w.status == WorkflowStatus.SME_APPROVED

    def test_rejected_to_awaiting(self):
        w = _make_workflow(WorkflowStatus.SME_REJECTED)
        w.transition(WorkflowStatus.AWAITING_SME_AUDIT)
        assert w.status == WorkflowStatus.AWAITING_SME_AUDIT

    def test_orphaned_to_recertifying(self):
        w = _make_workflow(WorkflowStatus.ORPHANED)
        w.transition(WorkflowStatus.RECERTIFYING)
        assert w.status == WorkflowStatus.RECERTIFYING

    def test_recertifying_to_awaiting(self):
        w = _make_workflow(WorkflowStatus.RECERTIFYING)
        w.transition(WorkflowStatus.AWAITING_SME_AUDIT)
        assert w.status == WorkflowStatus.AWAITING_SME_AUDIT

    def test_full_edit_approval_chain(self):
        """AWAITING → EDITED → APPROVED (two-step edit flow)."""
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.SME_EDITED, actioned_by="sme@example.com")
        w.transition(WorkflowStatus.SME_APPROVED, actioned_by="sme@example.com")
        assert w.status == WorkflowStatus.SME_APPROVED

    def test_full_orphan_recertify_chain(self):
        """AWAITING → ORPHANED → RECERTIFYING → AWAITING."""
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.ORPHANED)
        w.transition(WorkflowStatus.RECERTIFYING)
        w.transition(WorkflowStatus.AWAITING_SME_AUDIT)
        assert w.status == WorkflowStatus.AWAITING_SME_AUDIT


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

class TestInvalidTransitions:
    @pytest.mark.parametrize("current,target", [
        (WorkflowStatus.SME_APPROVED, WorkflowStatus.AWAITING_SME_AUDIT),
        (WorkflowStatus.SME_APPROVED, WorkflowStatus.SME_EDITED),
        (WorkflowStatus.SME_APPROVED, WorkflowStatus.ORPHANED),
        (WorkflowStatus.SME_EDITED, WorkflowStatus.AWAITING_SME_AUDIT),
        (WorkflowStatus.SME_EDITED, WorkflowStatus.SME_REJECTED),
        (WorkflowStatus.SME_EDITED, WorkflowStatus.ORPHANED),
        (WorkflowStatus.ORPHANED, WorkflowStatus.SME_APPROVED),
        (WorkflowStatus.RECERTIFYING, WorkflowStatus.SME_APPROVED),
        (WorkflowStatus.AWAITING_SME_AUDIT, WorkflowStatus.RECERTIFYING),
    ])
    def test_invalid_raises(self, current, target):
        w = _make_workflow(current)
        with pytest.raises(InvalidTransitionError):
            w.transition(target)

    def test_error_message_contains_states(self):
        w = _make_workflow(WorkflowStatus.SME_APPROVED)
        with pytest.raises(InvalidTransitionError) as exc_info:
            w.transition(WorkflowStatus.AWAITING_SME_AUDIT)
        assert "SME_APPROVED" in str(exc_info.value)
        assert "AWAITING_SME_AUDIT" in str(exc_info.value)


# ---------------------------------------------------------------------------
# actioned_by and actioned_at
# ---------------------------------------------------------------------------

class TestActionedBy:
    def test_actioned_by_recorded_on_approve(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.SME_APPROVED, actioned_by="ron@example.com")
        assert w.action_by == "ron@example.com"

    def test_actioned_at_set_on_approve(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        before = datetime.now(timezone.utc)
        w.transition(WorkflowStatus.SME_APPROVED, actioned_by="sme@example.com")
        assert w.actioned_at is not None
        assert w.actioned_at >= before

    def test_actioned_by_none_on_orphan(self):
        """System-driven transitions (ORPHANED) don't set actioned_by."""
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.ORPHANED)
        assert w.action_by is None

    def test_actioned_at_none_on_orphan(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.transition(WorkflowStatus.ORPHANED)
        assert w.actioned_at is None


# ---------------------------------------------------------------------------
# is_sla_breached property
# ---------------------------------------------------------------------------

class TestSlaBreach:
    def test_not_breached_before_deadline(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.sla_deadline_at = datetime.now(timezone.utc) + timedelta(hours=24)
        assert w.is_sla_breached is False

    @freeze_time("2026-06-02 12:00:00")
    def test_breached_after_deadline(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.sla_deadline_at = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)  # yesterday
        assert w.is_sla_breached is True

    def test_not_breached_when_no_deadline(self):
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.sla_deadline_at = None
        assert w.is_sla_breached is False

    def test_not_breached_when_already_approved(self):
        """A completed workflow is never 'breached' even if deadline has passed."""
        w = _make_workflow(WorkflowStatus.SME_APPROVED)
        w.sla_deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert w.is_sla_breached is False

    @freeze_time("2026-06-02 12:00:00")
    def test_exactly_at_deadline_not_breached(self):
        """Breach is strictly after deadline (>), not at."""
        w = _make_workflow(WorkflowStatus.AWAITING_SME_AUDIT)
        w.sla_deadline_at = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
        assert w.is_sla_breached is False


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS completeness
# ---------------------------------------------------------------------------

class TestValidTransitionsMap:
    def test_all_statuses_have_entry(self):
        for status in WorkflowStatus:
            assert status in VALID_TRANSITIONS, f"{status} missing from VALID_TRANSITIONS"

    def test_approved_is_terminal(self):
        assert VALID_TRANSITIONS[WorkflowStatus.SME_APPROVED] == set()
