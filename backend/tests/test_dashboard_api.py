"""The dashboard: every number comes from the database, is labelled, and is permission-gated."""

from apps.core.models import ReferenceFigure
from apps.organisation.models import Position, StaffAssignment
from tests.approvals_helpers import chain, draft_and_submit, new_department
from tests.conftest import give_role

URL = "/api/v1/dashboard/"


def figures(client):
    return {f["key"]: f for f in client.get(URL).json()["figures"]}


def test_reference_figures_are_seeded_unverified(db):
    rows = {r.key: (r.value, r.is_verified) for r in ReferenceFigure.objects.all()}
    assert rows == {
        "total_children": (85, False),
        "residential_children": (42, False),
        "outreach_children": (43, False),
        "total_employees": (15, False),
    }


def test_anonymous_is_refused(new_client):
    assert new_client().get(URL).status_code in (401, 403)


def test_children_figures_are_reference_and_labelled(staff):
    _, client = staff("EXECUTIVE_DIRECTOR")
    data = figures(client)
    for key, value in (
        ("total_children", 85),
        ("residential_children", 42),
        ("outreach_children", 43),
    ):
        assert data[key]["value"] == value
        assert data[key]["source"] == "reference"
        assert data[key]["source_label"] == "Reference figure (not yet verified)"
        assert data[key]["is_verified"] is False


def test_verified_reference_is_labelled_verified(staff):
    ReferenceFigure.objects.filter(key="total_children").update(is_verified=True)
    _, client = staff("EXECUTIVE_DIRECTOR")
    assert figures(client)["total_children"]["source_label"] == "Reference figure (verified)"


def test_employees_switch_to_a_live_count_from_the_database(staff, make_user):
    _, client = staff("EXECUTIVE_DIRECTOR")
    assert figures(client)["total_employees"]["source"] == "reference"
    assert figures(client)["total_employees"]["value"] == 15
    department = new_department()
    position = Position.objects.create(title="Clerk", department=department)
    for name in ("aaa1", "aaa2", "aaa3"):
        StaffAssignment.objects.create(
            user=make_user(name), position=position, department=department, start_date="2026-01-01"
        )
    ended = make_user("gone")
    StaffAssignment.objects.create(
        user=ended,
        position=position,
        department=department,
        start_date="2025-01-01",
        end_date="2025-06-01",
    )
    employees = figures(client)["total_employees"]
    assert employees["value"] == 3 and employees["source"] == "live"
    assert employees["reference_value"] == 15  # the old figure stays visible for comparison


def test_nothing_is_invented_for_modules_that_do_not_exist(staff):
    _, client = staff("EXECUTIVE_DIRECTOR")
    body = client.get(URL).json()
    assert "active_projects" in {f["key"] for f in body["figures"]}
    projects = {f["key"]: f for f in body["figures"]}["active_projects"]
    assert projects["value"] is None and projects["source"] == "none"
    assert projects["source_label"] == "No data yet"


def test_finance_is_absent_for_people_without_finance_view(staff):
    for role in ("STOREKEEPER", "SOCIAL_WELFARE_OFFICER", "HR_OFFICER", "ADMINISTRATOR"):
        _, client = staff(role)
        assert client.get(URL).json()["finance"] is None, role
    _, finance = staff("FINANCE_OFFICER")
    body = finance.get(URL).json()
    assert body["finance"]["figures"] == [] and "No financial records" in body["finance"]["note"]


def test_a_department_limited_finance_grant_sees_no_institution_totals(staff, departments):
    _, client = staff("PROJECT_MANAGER", department=departments["A"])  # finance VIEW: DEPARTMENT
    assert client.get(URL).json()["finance"] is None


def test_different_roles_get_different_content(staff):
    _, welfare = staff("SOCIAL_WELFARE_OFFICER")
    keys = {f["key"] for f in welfare.get(URL).json()["figures"]}
    assert keys == {"total_children", "residential_children", "outreach_children"}
    _, hr = staff("HR_OFFICER")
    assert {f["key"] for f in hr.get(URL).json()["figures"]} == {"total_employees"}
    _, store = staff("STOREKEEPER")
    assert store.get(URL).json()["figures"] == []
    _, board = staff("BOARD_MEMBER")
    assert {f["key"] for f in board.get(URL).json()["figures"]} == {"active_projects"}


def test_pending_approvals_are_counted_from_real_requests(staff, make_user):
    department = new_department()
    head_user, head = staff("PROJECT_MANAGER", username="head")
    department.head = head_user
    department.save()
    chain(department, ("DEPARTMENT_HEAD",))
    requester = make_user("req", department=department)
    give_role(requester, "STOREKEEPER")
    assert head.get(URL).json()["approvals"]["waiting_for_me"] == 0
    draft_and_submit(requester)
    draft_and_submit(requester, title="Second")
    approvals = head.get(URL).json()["approvals"]
    assert approvals["waiting_for_me"] == 2
    _, stores = staff("STOREKEEPER", department=department, username="other")
    assert stores.get(URL).json()["approvals"]["waiting_for_me"] == 0


def test_recent_activity_is_only_for_audit_viewers_and_scoped(staff):
    _, store = staff("STOREKEEPER")
    assert store.get(URL).json()["recent_activity"] is None
    _, admin = staff("ADMINISTRATOR")
    activity = admin.get(URL).json()["recent_activity"]
    assert activity and {"actor", "event_type", "occurred_at"} <= set(activity[0])
    assert "changes" not in activity[0] and "ip_address" not in activity[0]


def test_notifications_are_the_users_own(staff, make_user):
    from apps.approvals.models import Notification

    me, client = staff("STOREKEEPER")
    other = make_user("other")
    Notification.objects.create(user=me, title="Mine")
    Notification.objects.create(user=other, title="Theirs")
    body = client.get(URL).json()["notifications"]
    assert body["unread"] == 1 and [n["title"] for n in body["latest"]] == ["Mine"]


def test_department_dashboard_content_and_access(staff, make_user, departments):
    own, other = departments["A"], departments["B"]
    chain(own, ("DEPARTMENT_HEAD",))
    head_user, _ = staff("PROJECT_MANAGER", username="head", department=own)
    own.head = head_user
    own.save()
    requester = make_user("req", department=own)
    position = Position.objects.create(title="Clerk", department=own)
    StaffAssignment.objects.create(
        user=requester, position=position, department=own, start_date="2026-01-01"
    )
    give_role(requester, "STOREKEEPER")
    draft_and_submit(requester)

    _, member = staff("STOREKEEPER", department=own, username="member")
    body = member.get(f"{URL}departments/{own.pk}/").json()
    assert body["department"]["name"] == "Department A"
    assert body["staff_count"] == 1
    assert body["pending_approvals"]["count"] == 1
    assert body["recent_activity"] is None  # no audit permission
    assert member.get(f"{URL}departments/{other.pk}/").status_code == 404

    _, ed = staff("EXECUTIVE_DIRECTOR", username="director")
    seen = ed.get(f"{URL}departments/{other.pk}/")
    assert seen.status_code == 200 and seen.json()["pending_approvals"]["count"] == 0
    assert isinstance(ed.get(f"{URL}departments/{own.pk}/").json()["recent_activity"], list)
    assert ed.get(f"{URL}departments/00000000-0000-0000-0000-000000000000/").status_code == 404
