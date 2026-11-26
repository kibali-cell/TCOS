"""Sensitive role grants (D-044), TZS limits (D-020), access review, concurrency."""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.approvals.models import ApprovalRequest, TzsLimitPolicy
from apps.audit.models import AuditEvent
from apps.rbac.models import Permission, Role, RolePermission, UserRole
from tests.approvals_helpers import draft_and_submit, new_department, url
from tests.conftest import PASSWORD, delete, post, put

pytestmark = pytest.mark.django_db


@pytest.fixture
def org(staff, make_user):
    dept = new_department("GOV", "Governance")
    admin, admin_client = staff("ADMINISTRATOR", username="ada", department=dept)
    ed, ed_client = staff("EXECUTIVE_DIRECTOR", username="edith", department=dept)
    board, board_client = staff("BOARD_MEMBER", username="boris")
    newcomer = make_user("nina", department=dept)
    return {
        "dept": dept,
        "admin": admin,
        "ac": admin_client,
        "ed": ed,
        "ec": ed_client,
        "board": board,
        "bc": board_client,
        "newcomer": newcomer,
    }


def role_id(code):
    return str(Role.objects.get(code=code).pk)


def roles_url(user):
    return f"/api/v1/rbac/users/{user.pk}/roles/"


def grant_request(client, person, code, **extra):
    return post(
        client,
        url("role-grants"),
        {"user": str(person.pk), "role": role_id(code), "reason": "Joins the team", **extra},
    )


# --- No unilateral grant of sensitive roles --------------------------------------------


def test_an_administrator_cannot_directly_assign_a_sensitive_role(org):
    response = post(org["ac"], roles_url(org["newcomer"]), {"role": role_id("MEDICAL_OFFICER")})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert not UserRole.objects.filter(user=org["newcomer"]).exists()


def test_a_non_sensitive_role_can_still_be_assigned_directly(org):
    response = post(org["ac"], roles_url(org["newcomer"]), {"role": role_id("STOREKEEPER")})
    assert response.status_code == 201


def test_sensitivity_is_visible_on_roles(org):
    roles = {r["code"]: r for r in org["ac"].get("/api/v1/rbac/roles/").json()["results"]}
    assert roles["MEDICAL_OFFICER"]["is_sensitive"] is True
    assert roles["STOREKEEPER"]["is_sensitive"] is False
    assert any("medical" in reason for reason in roles["MEDICAL_OFFICER"]["sensitive_reasons"])


def test_administrator_cannot_ask_for_a_sensitive_role_for_themselves(org):
    response = grant_request(org["ac"], org["admin"], "MEDICAL_OFFICER")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_escalation"


def test_grant_needs_a_second_person_and_then_takes_effect(org):
    created = grant_request(
        org["ac"],
        org["newcomer"],
        "MEDICAL_OFFICER",
        valid_to=str(date.today() + timedelta(days=90)),
    )
    assert created.status_code == 201
    request = created.json()
    assert request["request_type"] == "ROLE_GRANT" and request["risk_level"] == "HIGH"
    assert request["payload"]["role"] == "Medical Officer"
    assert not UserRole.objects.filter(user=org["newcomer"]).exists()  # nothing granted yet

    # the administrator who asked cannot approve (no permission, and the rules say no)
    approve = url("requests", request["id"], "approve")
    assert post(org["ac"], approve, {"password": PASSWORD}).status_code in (403, 404)
    # the person receiving the role cannot approve either (not an approver at all)
    # a second person must; HIGH risk needs a fresh password
    assert post(org["ec"], approve, {}).status_code == 400
    done = post(org["ec"], approve, {"password": PASSWORD})
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"
    held = UserRole.objects.get(user=org["newcomer"], role__code="MEDICAL_OFFICER")
    assert held.granted_by_id == org["admin"].pk and held.valid_to is not None
    event = AuditEvent.objects.filter(event_type="ROLE_ASSIGNED").latest("id")
    assert event.metadata["approved_by"] == "edith" and event.metadata["requested_by"] == "ada"
    assert event.metadata["approval_request"] == done.json()["request_number"]


def test_rejected_grant_gives_nothing(org):
    request = grant_request(org["ac"], org["newcomer"], "FINANCE_OFFICER").json()
    rejected = post(
        org["ec"],
        url("requests", request["id"], "reject"),
        {"comment": "Not needed", "password": PASSWORD},
    )
    assert rejected.status_code == 200
    assert not UserRole.objects.filter(user=org["newcomer"]).exists()


def test_the_person_receiving_a_role_cannot_approve_it(org, staff):
    """An Executive Director cannot approve a grant that is for themselves."""
    ed2, ed2_client = staff("EXECUTIVE_DIRECTOR", username="edwin")
    request = grant_request(org["ac"], ed2, "FINANCE_OFFICER").json()
    approve = url("requests", request["id"], "approve")
    assert post(ed2_client, approve, {"password": PASSWORD}).status_code in (403, 404)
    assert post(org["bc"], approve, {"password": PASSWORD}).status_code == 200
    assert UserRole.objects.filter(user=ed2, role__code="FINANCE_OFFICER").exists()


def test_top_roles_need_a_board_member_not_the_director(org):
    request = grant_request(org["ac"], org["newcomer"], "ADMINISTRATOR").json()
    assert request["waiting_for"][0]["name"] == org["board"].full_name
    assert len(request["waiting_for"]) == 1
    approve = url("requests", request["id"], "approve")
    assert post(org["ec"], approve, {"password": PASSWORD}).status_code in (403, 404)
    assert post(org["bc"], approve, {"password": PASSWORD}).status_code == 200


def test_no_approver_available_means_no_request(staff, make_user):
    admin, client = staff("ADMINISTRATOR", username="lonely")
    person = make_user("someone")
    response = grant_request(client, person, "MEDICAL_OFFICER")
    assert response.status_code == 400 and "Nobody is available" in str(response.json())
    assert ApprovalRequest.objects.count() == 0


def test_duplicate_open_requests_and_existing_holders_are_refused(org):
    assert grant_request(org["ac"], org["newcomer"], "FINANCE_OFFICER").status_code == 201
    assert grant_request(org["ac"], org["newcomer"], "FINANCE_OFFICER").status_code == 400


def test_other_users_cannot_raise_grants(org, staff):
    _user, client = staff("SOCIAL_WELFARE_OFFICER", username="swo")
    assert grant_request(client, org["newcomer"], "MEDICAL_OFFICER").status_code == 403


def test_a_role_with_holders_cannot_quietly_gain_sensitive_access(org):
    """Otherwise widening an existing role would hand its holders access without approval."""
    role = Role.objects.create(code="HELPER", name="Helper")
    RolePermission.objects.create(
        role=role, permission=Permission.objects.get(module="stores", action="VIEW"), scope="ALL"
    )
    grants = [
        {"module": "stores", "action": "VIEW", "scope": "ALL"},
        {"module": "medical", "action": "VIEW", "scope": "ALL"},
    ]
    path = f"/api/v1/rbac/roles/{role.pk}/grants/"
    # nobody holds it yet: fine, because granting it later needs approval
    assert put(org["ac"], path, {"grants": grants}).status_code == 200
    put(org["ac"], path, {"grants": grants[:1]})
    assert post(org["ac"], roles_url(org["newcomer"]), {"role": str(role.pk)}).status_code == 201
    refused = put(org["ac"], path, {"grants": grants})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "approval_required"
    # narrowing is always allowed
    assert put(org["ac"], path, {"grants": []}).status_code == 200


def test_revoking_is_not_gated(org):
    request = grant_request(org["ac"], org["newcomer"], "FINANCE_OFFICER").json()
    post(org["ec"], url("requests", request["id"], "approve"), {"password": PASSWORD})
    held = UserRole.objects.get(user=org["newcomer"])
    assert delete(org["ac"], f"{roles_url(org['newcomer'])}{held.pk}/").status_code == 204


def test_console_command_is_the_audited_exception(org, make_user):
    person = make_user("first.board")
    with pytest.raises(CommandError):
        call_command("grant_role_from_console", "first.board", "BOARD_MEMBER", "--reason", "short")
    call_command(
        "grant_role_from_console",
        "first.board",
        "BOARD_MEMBER",
        "--reason",
        "First Board Member at setup",
    )
    assert UserRole.objects.filter(user=person, role__code="BOARD_MEMBER").exists()
    event = AuditEvent.objects.filter(event_type="ROLE_ASSIGNED").latest("id")
    assert "console" in event.metadata["via"] and event.metadata["reason"]


# --- TZS limits ---------------------------------------------------------------------------


def propose(client, **values):
    data = {
        "low_max": 300_000,
        "medium_max": 3_000_000,
        "always_high": ["PAYROLL"],
        "reason": "Board guidance",
        **values,
    }
    return post(client, url("tzs-limits", "propose"), data)


def test_initial_limits_are_explicit_provisional_and_visible(org):
    view = org["ac"].get(url("tzs-limits")).json()
    active = view["active"]
    assert (active["low_max"], active["medium_max"]) == (200_000, 2_000_000)
    assert active["is_ratified"] is False and active["version_number"] == 1
    assert "password" in view["explanation"] and view["can_propose"] is True


def test_limits_change_only_after_a_second_person_approves(org):
    created = propose(org["ac"])
    assert created.status_code == 201
    pending = org["ac"].get(url("tzs-limits")).json()
    assert pending["pending"]["version_number"] == 2 and pending["active"]["low_max"] == 200_000
    assert propose(org["ac"], reason="again").status_code == 409  # one proposal at a time

    request = created.json()
    approve = url("requests", request["id"], "approve")
    assert post(org["ac"], approve, {"password": PASSWORD}).status_code in (403, 404)
    assert post(org["bc"], approve, {"password": PASSWORD}).status_code == 200

    now = org["ac"].get(url("tzs-limits")).json()
    assert now["active"]["version_number"] == 2 and now["active"]["is_ratified"] is True
    assert now["active"]["ratified_by"]["name"] == org["board"].full_name
    assert now["pending"] is None
    assert TzsLimitPolicy.objects.get(version_number=1).state == "SUPERSEDED"
    assert AuditEvent.objects.filter(event_type="TZS_POLICY_ACTIVATED").count() == 1


def test_new_limits_drive_the_risk_of_later_requests(org, staff):
    request = propose(org["ac"]).json()
    post(org["bc"], url("requests", request["id"], "approve"), {"password": PASSWORD})
    requester, _ = staff("SOCIAL_WELFARE_OFFICER", department=org["dept"], username="rita")
    assert draft_and_submit(requester, amount_tzs=250_000).risk_level == "LOW"
    assert draft_and_submit(requester, amount_tzs=250_000).payload["tzs_policy_version"] == 2
    assert draft_and_submit(requester, kind="PAYROLL", amount_tzs=1).risk_level == "HIGH"
    assert draft_and_submit(requester, kind="WRITE_OFF", amount_tzs=1).risk_level == "LOW"


def test_rejected_limits_leave_the_old_ones_in_force(org):
    request = propose(org["ac"]).json()
    post(
        org["ec"],
        url("requests", request["id"], "reject"),
        {"comment": "Too high", "password": PASSWORD},
    )
    view = org["ac"].get(url("tzs-limits")).json()
    assert view["active"]["version_number"] == 1 and view["pending"] is None
    assert view["history"][0]["state"] == "REJECTED"
    assert propose(org["ac"]).status_code == 201  # a new proposal can follow


def test_proposal_rules_and_who_may_propose(org, staff):
    assert propose(org["ac"], low_max=500, medium_max=400).status_code == 400
    assert propose(org["ac"], reason="  ").status_code == 400
    assert propose(org["ac"], always_high=["NOPE"]).status_code == 400
    _user, swo = staff("SOCIAL_WELFARE_OFFICER", username="swo2")
    assert propose(swo).status_code == 403
    same = propose(org["ac"], low_max=200_000, medium_max=2_000_000, always_high=[])
    assert same.status_code == 201  # not identical: the always-high list differs


def test_ratifying_the_current_numbers_is_allowed_once(org):
    always = sorted(TzsLimitPolicy.objects.get(version_number=1).always_high)
    first = propose(org["ac"], low_max=200_000, medium_max=2_000_000, always_high=always)
    assert first.status_code == 201  # same numbers, but not yet ratified: this ratifies them
    post(org["bc"], url("requests", first.json()["id"], "approve"), {"password": PASSWORD})
    assert org["ac"].get(url("tzs-limits")).json()["active"]["is_ratified"] is True
    again = propose(org["ac"], low_max=200_000, medium_max=2_000_000, always_high=always)
    assert again.status_code == 400


def test_a_proposer_cannot_approve_their_own_limits(org):
    request = propose(org["ec"]).json()  # the Executive Director proposes
    approve = url("requests", request["id"], "approve")
    assert post(org["ec"], approve, {"password": PASSWORD}).status_code == 403
    assert post(org["bc"], approve, {"password": PASSWORD}).status_code == 200


# --- Access review (data sovereignty) ----------------------------------------------------


def test_access_review_lists_who_can_reach_sensitive_data(org, staff):
    staff("MEDICAL_OFFICER", username="mona")
    review = org["ec"].get("/api/v1/rbac/access-review/").json()
    classes = {c["code"]: c for c in review["classes"]}
    assert "mona" in {p["username"] for p in classes["medical"]["people"]}
    assert "ada" not in {p["username"] for p in classes["medical"]["people"]}  # admin: no medical
    assert "never copied" in classes["children"]["stored"].lower()
    assert review["hosting"]["region"] is None and "open decision" in review["hosting"]["note"]
    assert any(role["name"] == "Medical Officer" for role in review["sensitive_roles"])
    assert AuditEvent.objects.filter(event_type="ACCESS_REVIEW_VIEWED").count() == 1


def test_access_review_needs_the_audit_permission_everywhere(org, staff):
    _user, client = staff("SOCIAL_WELFARE_OFFICER", username="swo3")
    assert client.get("/api/v1/rbac/access-review/").status_code == 403
    assert org["bc"].get("/api/v1/rbac/access-review/").status_code == 403  # Board: no audit


def test_hosting_region_is_shown_when_set(org, settings):
    settings.TCOS_HOSTING_REGION = "Kenya (Nairobi)"
    review = org["ec"].get("/api/v1/rbac/access-review/").json()
    assert review["hosting"]["region"] == "Kenya (Nairobi)"
