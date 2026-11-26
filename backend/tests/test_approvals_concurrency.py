"""Concurrency: real parallel database connections (not a single test transaction).

These tests commit for real, so the test database must be emptied afterwards. Emptying uses
TRUNCATE, which the audit and approval-history triggers refuse on purpose, so the truncate
triggers are switched off for the cleanup and switched back on straight after.
"""

import threading

import pytest
from django.db import connection

from apps.approvals import services
from apps.approvals.models import ApprovalRequest
from tests.approvals_helpers import draft_and_submit, new_department

TABLES = {
    "audit_auditevent": "audit_event_no_truncate",
    "approvals_approvalaction": "approval_action_no_truncate",
}


def _toggle(state):
    with connection.cursor() as cursor:
        for table, trigger in TABLES.items():
            cursor.execute(f"ALTER TABLE {table} {state} TRIGGER {trigger}")


@pytest.fixture(autouse=True)
def _triggers_on():
    """Start every test here with the protections on (a previous cleanup switched them off)."""
    _toggle("ENABLE")


@pytest.fixture
def truncate_allowed():
    """Torn down just before the database is emptied, so TRUNCATE is allowed then.

    pytest-django runs transactional tests after all others, and the test database is
    destroyed at the end of the run, so nothing else sees the protections switched off.
    """
    yield
    _toggle("DISABLE")


pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)


def _in_threads(jobs):
    results = [None] * len(jobs)

    def run(index, job):
        try:
            results[index] = ("ok", job())
        except Exception as error:  # noqa: BLE001 - the test inspects what happened
            results[index] = ("error", error)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_request_numbers_are_unique_under_parallel_submission(truncate_allowed, staff):
    dept = new_department("CC", "Concurrency")
    requester, _ = staff("SOCIAL_WELFARE_OFFICER", department=dept, username="crew1")
    staff("EXECUTIVE_DIRECTOR", username="ced")
    drafts = [services.create_draft(requester, {"title": f"R{i}"})[0].pk for i in range(8)]
    results = _in_threads([lambda pk=pk: services.submit(requester, pk) for pk in drafts])
    assert all(kind == "ok" for kind, _ in results), results
    numbers = list(ApprovalRequest.objects.values_list("request_number", flat=True))
    assert len(numbers) == len(set(numbers)) == 8
    assert sorted(n[-6:] for n in numbers) == [f"{i:06d}" for i in range(1, 9)]


def test_two_simultaneous_approvals_decide_exactly_once(truncate_allowed, staff):
    dept = new_department("CD", "Concurrency Two")
    requester, _ = staff("SOCIAL_WELFARE_OFFICER", department=dept, username="crew2")
    ed1, _ = staff("EXECUTIVE_DIRECTOR", username="ced1")
    ed2, _ = staff("EXECUTIVE_DIRECTOR", username="ced2")
    request = draft_and_submit(requester, amount_tzs=1)
    results = _in_threads(
        [
            lambda: services.approve(ed1, request.pk),
            lambda: services.approve(ed2, request.pk),
        ]
    )
    assert sorted(kind for kind, _ in results) == ["error", "ok"], results
    request.refresh_from_db()
    assert request.status == "APPROVED"
    assert request.actions.filter(action="APPROVE").count() == 1
