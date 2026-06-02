"""
Celery application configuration.

Queues:
  drafting  — SoI generation tasks (CPU/network bound, scales horizontally)
  sla       — SLA monitor beat tasks (low-volume, time-sensitive)
  notify    — notification dispatch (fire-and-forget)
  analysis  — offline SME edit analysis (lowest priority)
"""

from celery import Celery
from metadata_architect.config import get_settings


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "metadata_architect",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,           # re-queue on worker crash
        worker_prefetch_multiplier=1,  # fair dispatch for long-running drafting tasks
        task_routes={
            "metadata_architect.workers.tasks.draft_asset_metadata": {"queue": "drafting"},
            "metadata_architect.workers.tasks.draft_asset_metadata_escalated": {"queue": "drafting"},
            "metadata_architect.workers.tasks.run_sla_monitor": {"queue": "sla"},
            "metadata_architect.workers.tasks.dispatch_orphan_notice": {"queue": "notify"},
            "metadata_architect.workers.tasks.analyse_sme_edit": {"queue": "analysis"},
        },
        beat_schedule={
            "sla-monitor-every-15min": {
                "task": "metadata_architect.workers.tasks.run_sla_monitor",
                "schedule": 900,  # every 15 minutes
            }
        },
    )
    return app


celery_app = make_celery()
