"""Approval Centre: lifecycle, separation of duties, routing, history, notifications."""

import uuid

import pytest
from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError

from apps.approvals import services
from apps.approvals.models import ApprovalAction, ApprovalRequest, Notification
from apps.audit.models import AuditEvent
from tests.approvals_helpers import chain, draft_and_submit, new_department, url
from tests.conftest import PASSWORD, give_role, patch, post

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(staff, make_user):
    """Department with a head and a two-step route: head, then Executive Director."""
    dept = new_department()
    requester, requester_client = staff("SOCIAL_WELFARE_OFFICER", department=dept, username="rita")
    head, head_client = staff("FINANCE_OFFICER", department=dept, username="harry")
    dept.head = head
    dept.save()
    ed, ed_client = staff("EXECUTIVE_DIRECTOR", username="edith", department=dept)
    board, board_client = staff("BOARD_MEMBER", username="boris")
    chain(dept, ("DEPARTMENT_HEAD",), ("ROLE", "EXECUTIVE_DIRECTOR"))
    return {
        "dept": dept,
        "requester": requester,
        "rc": requester_client,
        "head": head,
        "hc": head_client,
        "ed": ed,
        "ec": ed_client,
        "board": board,
        "bc": board_client,
    }


def body(response):
    assert response.status_code < 300, response.content
    return response.json()


# --- Creating and submitting ----------------------------------------------------------


def test_draft_creation_is_idempotent_and_private(world, staff):
    key = str(uuid.uuid4())
    first = post(world["rc"], url("requests"), {"id": key, "title": "Chairs"})
    again = post(world["rc"], url("requests"), {"id": key, "title": "Chairs"})
    assert (first.status_code, again.status_code) == (201, 200)
    assert ApprovalRequest.objects.filter(pk=key).count() == 1
    assert first.json()["status"] == "DRAFT" and first.json()["request_number"] is None
    # another person cannot take over or probe the same id
    assert post(world["hc"], url("requests"), {"id": key, "title": "x"}).status_code == 409


def test_submit_issues_number_route_and_approver_from_the_server(world):
    r = draft_and_submit(world["requester"])
    assert r.status == "SUBMITTED" and r.current_step == 1
    assert r.request_number.startswith("TCOS-REQ-") and len(r.request_number) == 20
    assert [e["label"] for e in r.route] == ["Head of the department", "Role: Executive Director"]
    assert list(r.assignees.values_list("user", flat=True)) == [world["head"].pk]


def test_a_client_cannot_choose_the_approver_number_or_risk(world):
    response = post(
        world["rc"],
        url("requests"),
        {
            "title": "Sneaky",
            "request_number": "TCOS-REQ-1999-000001",
            "risk_level": "LOW",
            "assigned_approver": str(world["requester"].pk),
            "status": "APPROVED",
            "amount_tzs": 9_000_000,
        },
    )
    row = ApprovalRequest.objects.get(pk=response.json()["id"])
    assert row.status == "DRAFT" and row.request_number is None
    submitted = services.submit(world["requester"], row.pk)
    assert submitted.risk_level == "HIGH" and submitted.request_number != "TCOS-REQ-1999-000001"


@pytest.mark.parametrize(
    ("amount", "kind", "risk"),
    [
        (None, "", "LOW"),
        (200_000, "", "LOW"),
        (200_001, "", "MEDIUM"),
        (2_000_000, "", "MEDIUM"),
        (2_000_001, "", "HIGH"),
        (10, "PAYROLL", "HIGH"),
        (10, "DONOR_REFUND", "HIGH"),
    ],
)
def test_risk_level_follows_the_active_tzs_limits(world, amount, kind, risk):
    r = draft_and_submit(world["requester"], amount_tzs=amount, kind=kind)
    assert r.risk_level == risk
    assert r.payload["tzs_policy_version"] == 1  # which limits were applied is on the record


def test_only_the_requester_can_edit_and_only_while_a_draft(world):
    row, _ = services.create_draft(world["requester"], {"title": "A"})
    response = patch(world["hc"], url("requests", row.pk), {"title": "B"})
    assert response.status_code == 404  # out of sight: the head has no business in a draft
    r = draft_and_submit(world["requester"])
    with pytest.raises(services.StateConflict):
        services.update_draft(world["requester"], r.pk, {"title": "changed"})


def test_cannot_submit_twice_or_someone_elses_draft(world):
    row, _ = services.create_draft(world["requester"], {"title": "A"})
    with pytest.raises(Exception, match="person who raised"):
        services.submit(world["head"], row.pk)
    services.submit(world["requester"], row.pk)
    with pytest.raises(services.StateConflict):
        services.submit(world["requester"], row.pk)


# --- Separation of duties ---------------------------------------------------------------


def test_requester_cannot_approve_reject_or_review_their_own_request(world):
    r = draft_and_submit(world["requester"])
    for action in ("approve", "reject", "review"):
        response = post(world["rc"], url("requests", r.pk, action), {"comment": "me"})
        assert response.status_code == 403, action
        assert response.json()["error"]["code"] == "self_decision"
    r.refresh_from_db()
    assert r.status == "SUBMITTED"
    refusals = AuditEvent.objects.filter(event_type="APPROVAL_REFUSED", success=False)
    assert refusals.count() == 3  # every attempt is on the record


def test_requester_is_refused_even_if_made_an_assignee(world):
    """Defence in depth: forcing a row in does not help; the service checks first."""
    from apps.approvals.models import ApprovalAssignee

    r = draft_and_submit(world["requester"])
    ApprovalAssignee.objects.create(request=r, user=world["requester"], step=1)
    with pytest.raises(Exception, match="own request"):
        services.approve(world["requester"], r.pk)


def test_the_database_itself_refuses_a_self_decision(world):
    r = draft_and_submit(world["requester"])
    with pytest.raises((InternalError, ProgrammingError), match="cannot APPROVE"):
        ApprovalAction.objects.create(
            request=r,
            action="APPROVE",
            actor=world["requester"],
            from_status="SUBMITTED",
            to_status="APPROVED",
        )


def test_wrong_person_cannot_decide(world):
    r = draft_and_submit(world["requester"])
    response = post(world["ec"], url("requests", r.pk, "approve"), {})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_assigned"  # step 2 person at step 1


def test_person_without_the_approve_permission_cannot_decide(world, staff):
    _clerk, client = staff("STOREKEEPER", department=world["dept"], username="clerk")
    r = draft_and_submit(world["requester"])
    # the clerk cannot even see it: no assignment, no scope
    assert post(client, url("requests", r.pk, "approve"), {}).status_code in (403, 404)
    assert world["hc"].get(url("requests", r.pk)).status_code == 200


# --- The route ----------------------------------------------------------------------------


def test_two_steps_then_approved_with_full_history(world):
    r = draft_and_submit(world["requester"])
    first = body(post(world["hc"], url("requests", r.pk, "approve"), {"comment": "ok"}))
    assert first["status"] == "UNDER_REVIEW" and first["current_step"] == 2
    assert [p["name"] for p in first["waiting_for"]] == [world["ed"].full_name]
    final = body(post(world["ec"], url("requests", r.pk, "approve"), {"comment": "fine"}))
    assert final["status"] == "APPROVED" and final["decided_at"]
    actions = [h["action"] for h in final["history"]]
    assert actions == ["CREATE", "SUBMIT", "APPROVE", "APPROVE"]
    assert final["history"][2]["actor"]["name"] == world["head"].full_name
    assert post(world["ec"], url("requests", r.pk, "approve"), {}).status_code == 409


def test_one_person_cannot_approve_two_steps_of_the_same_request(staff):
    dept = new_department("D2", "Dept Two")
    requester, _ = staff("SOCIAL_WELFARE_OFFICER", department=dept, username="req2")
    ed, _ = staff("EXECUTIVE_DIRECTOR", username="ed2")
    board, _ = staff("BOARD_MEMBER", username="board2")
    chain(dept, ("ROLE", "EXECUTIVE_DIRECTOR"), ("ROLE", "EXECUTIVE_DIRECTOR"))
    r = draft_and_submit(requester)
    r = services.approve(ed, r.pk)
    assert r.current_step == 2
    assert list(r.assignees.values_list("user", flat=True)) == [board.pk]  # escalated
    assert [a.action for a in r.actions.all()][-2:] == ["APPROVE", "ESCALATE"]


def test_rejection_needs_a_reason_and_ends_the_request(world):
    r = draft_and_submit(world["requester"])
    assert post(world["hc"], url("requests", r.pk, "reject"), {"comment": "  "}).status_code == 400
    done = body(post(world["hc"], url("requests", r.pk, "reject"), {"comment": "No budget"}))
    assert done["status"] == "REJECTED" and done["decision_comment"] == "No budget"
    assert post(world["hc"], url("requests", r.pk, "approve"), {}).status_code == 409
    assert post(world["rc"], url("requests", r.pk, "cancel"), {}).status_code == 409


def test_review_moves_to_under_review_once(world):
    r = draft_and_submit(world["requester"])
    assert body(post(world["hc"], url("requests", r.pk, "review"), {}))["status"] == "UNDER_REVIEW"
    assert post(world["hc"], url("requests", r.pk, "review"), {}).status_code == 409
    assert body(post(world["hc"], url("requests", r.pk, "approve"), {}))["current_step"] == 2


def test_cancel_rules(world):
    row, _ = services.create_draft(world["requester"], {"title": "A"})
    assert body(post(world["rc"], url("requests", row.pk, "cancel"), {}))["status"] == "CANCELLED"
    r = draft_and_submit(world["requester"])
    assert post(world["hc"], url("requests", r.pk, "cancel"), {}).status_code == 403
    assert body(post(world["rc"], url("requests", r.pk, "cancel"), {}))["status"] == "CANCELLED"
    done = draft_and_submit(world["requester"])
    services.approve(world["head"], done.pk)
    services.approve(world["ed"], done.pk)
    assert post(world["rc"], url("requests", done.pk, "cancel"), {}).status_code == 409


def test_high_risk_decisions_need_the_password_again(world):
    r = draft_and_submit(world["requester"], amount_tzs=5_000_000)
    path = url("requests", r.pk, "approve")
    assert post(world["hc"], path, {}).status_code == 400
    assert post(world["hc"], path, {"password": "wrong-password-1"}).status_code == 400
    assert post(world["hc"], path, {"password": PASSWORD}).status_code == 200


# --- Fallback and escalation -----------------------------------------------------------


def test_without_a_route_the_executive_director_decides_and_it_says_so(staff):
    dept = new_department("D3", "Dept Three")
    requester, _ = staff("SOCIAL_WELFARE_OFFICER", department=dept, username="req3")
    ed, _ = staff("EXECUTIVE_DIRECTOR", username="ed3")
    r = draft_and_submit(requester)
    assert "no approval route" in r.route[0]["label"]
    assert list(r.assignees.values_list("user", flat=True)) == [ed.pk]


def test_requester_who_is_the_only_approver_goes_up_a_level(staff):
    dept = new_department("D4", "Dept Four")
    ed, _ = staff("EXECUTIVE_DIRECTOR", department=dept, username="ed4")
    board, _ = staff("BOARD_MEMBER", username="board4")
    r = draft_and_submit(ed)
    assert list(r.assignees.values_list("user", flat=True)) == [board.pk]
    assert r.actions.filter(action="ESCALATE").count() == 1


def test_nobody_else_available_refuses_the_submission(staff):
    dept = new_department("D5", "Dept Five")
    ed, _ = staff("EXECUTIVE_DIRECTOR", department=dept, username="ed5")
    row, _ = services.create_draft(ed, {"title": "Mine"})
    with pytest.raises(Exception, match="Nobody is available"):
        services.submit(ed, row.pk)
    row.refresh_from_db()
    assert row.status == "DRAFT" and row.request_number is None


# --- Visibility and department restrictions --------------------------------------------


def test_lists_and_departments_are_scoped(world, staff):
    other = new_department("D6", "Dept Six")
    outsider, oc = staff("FINANCE_OFFICER", department=other, username="otto")
    r = draft_and_submit(world["requester"])
    assert oc.get(url("requests", r.pk)).status_code == 404
    assert oc.get(url("requests") + "?view=all").json()["count"] == 0
    assert world["rc"].get(url("requests") + "?view=mine").json()["count"] == 1
    assert world["hc"].get(url("requests") + "?view=pending").json()["count"] == 1
    assert world["ec"].get(url("requests") + "?view=pending").json()["count"] == 0
    assert world["ec"].get(url("requests") + "?view=all").json()["count"] == 1  # ED sees all
    assert world["hc"].get(url("requests", r.pk)).json()["can"]["approve"] is True
    assert world["rc"].get(url("requests", r.pk)).json()["can"]["approve"] is False


def test_search_and_filters(world):
    draft_and_submit(world["requester"], title="Roof repairs", amount_tzs=3_000_000)
    draft_and_submit(world["requester"], title="Pencils")
    rc = world["rc"]
    assert rc.get(url("requests") + "?search=roof").json()["count"] == 1
    assert rc.get(url("requests") + "?risk=high").json()["count"] == 1
    assert rc.get(url("requests") + "?status=draft").json()["count"] == 0


# --- History is append-only -------------------------------------------------------------


def test_history_cannot_be_changed_or_removed(world):
    r = draft_and_submit(world["requester"])
    action = r.actions.first()
    action.comment = "edited"
    with pytest.raises(RuntimeError):
        action.save()
    with pytest.raises(RuntimeError):
        action.delete()
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")  # settle the test's own pending checks
    for sql in (
        "UPDATE approvals_approvalaction SET comment = 'x'",
        "DELETE FROM approvals_approvalaction",
        "TRUNCATE approvals_approvalaction CASCADE",
    ):
        with pytest.raises((InternalError, ProgrammingError), match="append-only"):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql)
    assert r.actions.count() == 2


# --- Notifications -----------------------------------------------------------------------


def test_notifications_reach_the_right_people_and_only_they_read_them(world):
    r = draft_and_submit(world["requester"])
    assert Notification.objects.filter(user=world["head"], request=r).count() == 1
    assert world["hc"].get(url("summary")).json() == {"pending": 1, "unread_notifications": 1}
    services.reject(world["head"], r.pk, "Not now")
    mine = world["rc"].get(url("notifications")).json()["results"]
    assert mine[0]["title"].endswith("was rejected") and mine[0]["is_read"] is False
    assert post(world["ec"], url("notifications"), {}).status_code == 204  # someone else's inbox
    assert world["rc"].get(url("summary")).json()["unread_notifications"] == 1
    assert post(world["rc"], url("notifications"), {}).status_code == 204
    assert world["rc"].get(url("summary")).json()["unread_notifications"] == 0


def test_comments_are_for_participants_only(world):
    r = draft_and_submit(world["requester"])
    assert (
        post(world["hc"], url("requests", r.pk, "comment"), {"comment": "Quote?"}).status_code
        == 200
    )
    assert (
        post(world["rc"], url("requests", r.pk, "comment"), {"comment": "Attached"}).status_code
        == 200
    )
    assert post(world["ec"], url("requests", r.pk, "comment"), {"comment": "hi"}).status_code == 403
    assert r.actions.filter(action="COMMENT").count() == 2


# --- Audit -------------------------------------------------------------------------------


def test_every_transition_is_audited_in_the_same_step(world):
    r = draft_and_submit(world["requester"])
    services.approve(world["head"], r.pk)
    services.approve(world["ed"], r.pk)
    kinds = list(
        AuditEvent.objects.filter(object_id=str(r.pk))
        .order_by("id")
        .values_list("event_type", flat=True)
    )
    assert kinds == [
        "APPROVAL_CREATED",
        "APPROVAL_SUBMITTED",
        "APPROVAL_DECISION",
        "APPROVAL_DECISION",
    ]
    assert AuditEvent.objects.get(event_type="APPROVAL_SUBMITTED").metadata["request_number"]


def test_archiving_a_department_with_open_requests_is_blocked(world):
    from apps.organisation import services as org

    draft_and_submit(world["requester"])
    admin_like = world["ed"]
    with pytest.raises(Exception, match="still open"):
        org.archive_department(admin_like, world["dept"])


def test_give_role_helper_still_works_for_other_tests(world):
    assert give_role(world["requester"], "STOREKEEPER").pk
