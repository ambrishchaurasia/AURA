"""
AURA Structured Logger — Step-by-step action logging.

Every task execution is logged with structured JSON entries including:
- Task goal
- Each step with application, action, resolver tier, status
- Verification results
- Timing information
- Error details

Logs are stored in memory during execution and can be exported.
"""

from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from typing import Optional


class TaskLog:
    """Structured log for a single task execution."""

    def __init__(self, task_id: str, goal: str):
        self.task_id = task_id
        self.goal = goal
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at = None
        self.status = "running"
        self.steps = []
        self._current_step = None
        self._step_counter = 0

    def start_step(
        self,
        action: str,
        application: str = None,
        target: str = None,
        resolver_tier: int = None,
    ) -> dict:
        """Start a new step in the task."""
        self._step_counter += 1
        step = {
            "step_number": self._step_counter,
            "action": action,
            "application": application,
            "target": target,
            "resolver_tier": resolver_tier,
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "duration_ms": None,
            "details": None,
            "verification": None,
            "error": None,
        }
        self._current_step = step
        self.steps.append(step)

        _print_step_start(step)
        return step

    def complete_step(
        self,
        status: str = "success",
        details: str = None,
        verification: dict = None,
    ):
        """Mark the current step as completed."""
        if self._current_step is None:
            return

        step = self._current_step
        step["status"] = status
        step["details"] = details
        step["finished_at"] = time.time()
        step["duration_ms"] = round(
            (step["finished_at"] - step["started_at"]) * 1000
        )
        step["verification"] = verification

        _print_step_complete(step)
        self._current_step = None

    def fail_step(self, error: str, details: str = None):
        """Mark the current step as failed."""
        if self._current_step is None:
            return

        step = self._current_step
        step["status"] = "failure"
        step["error"] = error
        step["details"] = details
        step["finished_at"] = time.time()
        step["duration_ms"] = round(
            (step["finished_at"] - step["started_at"]) * 1000
        )

        _print_step_failure(step)
        self._current_step = None

    def finish(self, status: str = "completed"):
        """Mark the task as finished."""
        self.status = status
        self.finished_at = datetime.now(timezone.utc).isoformat()
        _print_task_finish(self)

    def to_dict(self) -> dict:
        """Export log as a dictionary."""
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_steps": len(self.steps),
            "steps": self.steps,
        }

    def to_json(self, indent: int = 2) -> str:
        """Export log as formatted JSON."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ── Console output helpers ──

def _print_step_start(step: dict):
    num = step["step_number"]
    action = step["action"]
    app = step.get("application") or ""
    target = step.get("target") or ""
    tier = step.get("resolver_tier")
    tier_str = f" [Tier {tier}]" if tier else ""

    print(f"\n  [Step {num}] {app} -> {action}{tier_str}")
    if target:
        print(f"           Target: {target}")


def _print_step_complete(step: dict):
    num = step["step_number"]
    duration = step.get("duration_ms", 0)
    details = step.get("details") or ""
    verification = step.get("verification")

    print(f"    [OK] Step {num}: SUCCESS ({duration}ms)")
    if details:
        print(f"      {details}")
    if verification:
        v_status = "[VERIFIED]" if verification.get("verified") else "[VERIFY FAILED]"
        print(f"      {v_status}: {verification.get('details', '')}")


def _print_step_failure(step: dict):
    num = step["step_number"]
    error = step.get("error") or "Unknown error"
    duration = step.get("duration_ms", 0)

    print(f"    [FAIL] Step {num}: FAILURE ({duration}ms)")
    print(f"      Error: {error}")


def _print_task_finish(log: TaskLog):
    total = len(log.steps)
    success = sum(1 for s in log.steps if s["status"] == "success")
    failed = sum(1 for s in log.steps if s["status"] == "failure")

    print(f"\n{'='*50}")
    print(f"  Task: {log.goal}")
    print(f"  Status: {log.status.upper()}")
    print(f"  Steps: {success}/{total} succeeded, {failed} failed")
    print(f"{'='*50}\n")
