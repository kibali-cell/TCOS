"""The permission engine: scopes, record grants and users holding several roles."""

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.rbac.models import Permission, RecordGrant, Role, RolePermission, UserRole
from apps.rbac.permissions import can, effective_permissions, filter_queryset, permissions_payload
from tests.rbac_testapp.models import Record

_counter = itertools.count(1)


def custom_role(*grants, active=True):
    """A fresh role with exactly these (module, action, scope) grants."""
    role = Role.objects.create(
        code=f"TEST_{next(_counter)}", name=f"Test role {next(_counter)}", is_active=active
    )
    for module, action, scope in grants:
        RolePermission.objects.create(
            role=role, permission=Permission.objects.get(module=module, action=action), scope=scope
        )
    return role


def hold(user, role, department=None, **extra):
    return UserRole.objects.create(user=user, role=role, department=department, **extra)


def make_record(title, department=None, created_by=None, assigned_to=None):
    return Record.objects.create(
        title=title, department=department, created_by=created_by, assigned_to=assigned_to
    )


@pytest.fixture
def people(make_user, departments):
    return {
        "me": make_user("me.user", department=departments["A"]),
        "other": make_user("other.user", department=departments["B"]),
    }


def visible(user, action="VIEW", module="finance"):
    return set(
        filter_queryset(user, module, action, Record.objects.all()).values_list("title", flat=True)
    )


# --- Single scopes -----------------------------------------------------------------------


def test_all_scope_reaches_every_record(people, departments):
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")))
    make_record("a", departments["A"])
    make_record("b", departments["B"])
    make_record("none")
    assert visible(people["me"]) == {"a", "b", "none"}


def test_department_scope_reaches_only_the_users_department(people, departments):
    hold(people["me"], custom_role(("finance", "VIEW", "DEPARTMENT")))
    make_record("in A", departments["A"])
    make_record("in B", departments["B"])
    make_record("no dept")
    assert visible(people["me"]) == {"in A"}


def test_department_scope_does_not_include_own_records_elsewhere(people, departments):
    hold(people["me"], custom_role(("finance", "VIEW", "DEPARTMENT")))
    make_record("mine but in B", departments["B"], created_by=people["me"])
    assert visible(people["me"]) == set()


def test_department_scope_with_no_department_reaches_nothing(make_user, departments):
    drifter = make_user("drifter")  # no department
    hold(drifter, custom_role(("finance", "VIEW", "DEPARTMENT")))
    make_record("x", departments["A"])
    assert visible(drifter) == set()
    # An empty grant is no grant: no menu entry either.
    assert not can(drifter, "finance", "VIEW")


def test_own_scope_reaches_only_records_the_user_created(people, departments):
    hold(people["me"], custom_role(("finance", "VIEW", "OWN")))
    make_record("mine", departments["B"], created_by=people["me"])
    make_record("theirs", departments["B"], created_by=people["other"])
    make_record("assigned to me", assigned_to=people["me"], created_by=people["other"])
    assert visible(people["me"]) == {"mine"}


def test_assigned_scope_reaches_assigned_and_own_records(people):
    hold(people["me"], custom_role(("finance", "VIEW", "ASSIGNED")))
    make_record("mine", created_by=people["me"])
    make_record("assigned to me", assigned_to=people["me"], created_by=people["other"])
    make_record("assigned to them", assigned_to=people["other"], created_by=people["other"])
    assert visible(people["me"]) == {"mine", "assigned to me"}


def test_scope_applies_per_action(people, departments):
    hold(
        people["me"],
        custom_role(("finance", "VIEW", "ALL"), ("finance", "EDIT", "DEPARTMENT")),
    )
    in_a = make_record("in A", departments["A"])
    in_b = make_record("in B", departments["B"])
    assert can(people["me"], "finance", "VIEW", in_b)
    assert can(people["me"], "finance", "EDIT", in_a)
    assert not can(people["me"], "finance", "EDIT", in_b)
    assert not can(people["me"], "finance", "DELETE", in_a)


def test_permission_in_one_module_does_not_leak_to_another(people):
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")))
    assert can(people["me"], "finance", "VIEW")
    assert not can(people["me"], "medical", "VIEW")
    assert not can(people["me"], "finance", "EXPORT")


def test_user_with_no_roles_has_no_access(people):
    assert effective_permissions(people["me"]) == {}
    assert not can(people["me"], "finance", "VIEW")
    assert visible(people["me"]) == set()


def test_unknown_action_and_anonymous_are_denied(people):
    from django.contrib.auth.models import AnonymousUser

    hold(people["me"], custom_role(("finance", "VIEW", "ALL")))
    assert not can(people["me"], "finance", "TELEPORT")
    assert not can(AnonymousUser(), "finance", "VIEW")
    assert not can(None, "finance", "VIEW")
    assert filter_queryset(AnonymousUser(), "finance", "VIEW", Record.objects.all()).count() == 0


def test_inactive_account_loses_all_access(people):
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")))
    User.objects.filter(pk=people["me"].pk).update(status="INACTIVE")
    people["me"].refresh_from_db()
    assert effective_permissions(people["me"]) == {}
    assert not can(people["me"], "finance", "VIEW")


# --- Record grants ---------------------------------------------------------------------


def grant(user, record, action="VIEW", **extra):
    from django.contrib.contenttypes.models import ContentType

    return RecordGrant.objects.create(
        user=user,
        content_type=ContentType.objects.get_for_model(Record),
        object_id=record.pk,
        action=action,
        **extra,
    )


def test_record_grant_gives_one_record_and_one_action_only(people, departments):
    secret = make_record("secret", departments["B"])
    other = make_record("other", departments["B"])
    grant(people["me"], secret, "VIEW")

    assert can(people["me"], "finance", "VIEW", secret)
    assert not can(people["me"], "finance", "VIEW", other)  # different record
    assert not can(people["me"], "finance", "EDIT", secret)  # different action
    assert visible(people["me"]) == {"secret"}


def test_record_grant_is_for_that_user_only(people):
    record = make_record("secret")
    grant(people["me"], record)
    assert not can(people["other"], "finance", "VIEW", record)


def test_expired_and_revoked_record_grants_stop_working(people):
    expired = make_record("expired")
    revoked = make_record("revoked")
    live = make_record("live")
    grant(people["me"], expired, expires_at=timezone.now() - timedelta(minutes=1))
    grant(people["me"], revoked, revoked_at=timezone.now())
    grant(people["me"], live, expires_at=timezone.now() + timedelta(hours=1))

    assert visible(people["me"]) == {"live"}
    assert not can(people["me"], "finance", "VIEW", expired)
    assert not can(people["me"], "finance", "VIEW", revoked)


def test_record_grant_adds_to_role_scope(people, departments):
    hold(people["me"], custom_role(("finance", "VIEW", "DEPARTMENT")))
    make_record("in A", departments["A"])
    extra = make_record("in B", departments["B"])
    grant(people["me"], extra)
    assert visible(people["me"]) == {"in A", "in B"}


def test_record_grant_does_not_create_module_level_permission(people):
    record = make_record("x")
    grant(people["me"], record)
    assert not can(people["me"], "finance", "VIEW")  # no list access to the module


# --- Several roles per user ------------------------------------------------------------


def test_permissions_are_the_union_of_all_roles(people):
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")))
    hold(people["me"], custom_role(("stores", "EDIT", "ALL")))
    assert can(people["me"], "finance", "VIEW")
    assert can(people["me"], "stores", "EDIT")
    assert not can(people["me"], "finance", "EDIT")
    assert set(effective_permissions(people["me"])) == {("finance", "VIEW"), ("stores", "EDIT")}


def test_widest_scope_wins_for_the_same_permission(people, departments):
    hold(people["me"], custom_role(("finance", "VIEW", "OWN")))
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")))
    make_record("elsewhere", departments["B"])
    assert visible(people["me"]) == {"elsewhere"}
    assert permissions_payload(effective_permissions(people["me"]))["finance"]["VIEW"] == "ALL"


def test_narrow_scopes_combine_rather_than_replace(people, departments):
    hold(people["me"], custom_role(("finance", "VIEW", "DEPARTMENT")))
    hold(people["me"], custom_role(("finance", "VIEW", "OWN")))
    make_record("in A", departments["A"])
    make_record("mine in B", departments["B"], created_by=people["me"])
    make_record("theirs in B", departments["B"], created_by=people["other"])
    assert visible(people["me"]) == {"in A", "mine in B"}


def test_department_restricted_role_plus_unrestricted_role(people, departments):
    """The restricted role stays confined to its department; the other role is unaffected."""
    view_all = custom_role(("finance", "VIEW", "ALL"))
    edit_all = custom_role(("finance", "EDIT", "ALL"))
    hold(people["me"], view_all)  # VIEW everywhere
    hold(people["me"], edit_all, department=departments["B"])  # EDIT only in B
    in_a = make_record("in A", departments["A"])
    in_b = make_record("in B", departments["B"])

    assert can(people["me"], "finance", "VIEW", in_a) and can(people["me"], "finance", "VIEW", in_b)
    assert can(people["me"], "finance", "EDIT", in_b)
    assert not can(people["me"], "finance", "EDIT", in_a)
    assert visible(people["me"], "EDIT") == {"in B"}


def test_same_role_in_two_departments_unites_them(people, departments):
    role = custom_role(("finance", "VIEW", "ALL"))
    hold(people["me"], role, department=departments["A"])
    hold(people["me"], role, department=departments["B"])
    make_record("a", departments["A"])
    make_record("b", departments["B"])
    make_record("none")
    assert visible(people["me"]) == {"a", "b"}


def test_department_scope_follows_the_role_assignments_department(people, departments):
    """DEPARTMENT scope uses the department named on the assignment, not the home department."""
    role = custom_role(("finance", "VIEW", "DEPARTMENT"))
    hold(people["me"], role, department=departments["B"])  # home department is A
    make_record("in A", departments["A"])
    make_record("in B", departments["B"])
    assert visible(people["me"]) == {"in B"}


def test_expired_role_stops_applying(people):
    today = timezone.localdate()
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")), valid_to=today - timedelta(days=1))
    assert not can(people["me"], "finance", "VIEW")


def test_role_not_yet_valid_does_not_apply(people):
    today = timezone.localdate()
    hold(
        people["me"], custom_role(("finance", "VIEW", "ALL")), valid_from=today + timedelta(days=1)
    )
    assert not can(people["me"], "finance", "VIEW")


def test_role_valid_today_applies_on_both_boundary_days(people):
    today = timezone.localdate()
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")), valid_from=today, valid_to=today)
    assert can(people["me"], "finance", "VIEW")


def test_expiring_one_role_leaves_the_others_intact(people):
    today = timezone.localdate()
    hold(people["me"], custom_role(("finance", "VIEW", "ALL")), valid_to=today - timedelta(days=1))
    hold(people["me"], custom_role(("stores", "VIEW", "ALL")))
    assert not can(people["me"], "finance", "VIEW")
    assert can(people["me"], "stores", "VIEW")


def test_revoking_one_role_leaves_the_others_intact(people):
    finance = hold(people["me"], custom_role(("finance", "VIEW", "ALL")))
    hold(people["me"], custom_role(("stores", "VIEW", "ALL")))
    finance.revoked_at = timezone.now()
    finance.save()
    assert not can(people["me"], "finance", "VIEW")
    assert can(people["me"], "stores", "VIEW")


def test_deactivating_a_role_stops_it_applying_for_everyone(people):
    role = custom_role(("finance", "VIEW", "ALL"))
    hold(people["me"], role)
    hold(people["other"], role)
    Role.objects.filter(pk=role.pk).update(is_active=False)
    assert not can(people["me"], "finance", "VIEW")
    assert not can(people["other"], "finance", "VIEW")


def test_a_changed_role_takes_effect_on_the_next_check(people):
    role = custom_role(("finance", "VIEW", "ALL"))
    hold(people["me"], role)
    assert can(people["me"], "finance", "VIEW")
    RolePermission.objects.filter(role=role).delete()
    assert not can(people["me"], "finance", "VIEW")  # same user object, no stale cache


# --- can() and filter_queryset() must always agree ---------------------------------------


SCENARIOS = {
    "all": [(("finance", "VIEW", "ALL"), None)],
    "department": [(("finance", "VIEW", "DEPARTMENT"), None)],
    "own": [(("finance", "VIEW", "OWN"), None)],
    "assigned": [(("finance", "VIEW", "ASSIGNED"), None)],
    "restricted all": [(("finance", "VIEW", "ALL"), "B")],
    "department + own": [
        (("finance", "VIEW", "DEPARTMENT"), None),
        (("finance", "VIEW", "OWN"), None),
    ],
    "restricted all + assigned": [
        (("finance", "VIEW", "ALL"), "A"),
        (("finance", "VIEW", "ASSIGNED"), None),
    ],
    "nothing": [],
}


@pytest.mark.parametrize("name", list(SCENARIOS))
@pytest.mark.parametrize("with_record_grant", [False, True])
def test_can_and_filter_queryset_agree_on_every_record(
    people, departments, name, with_record_grant
):
    for spec, dept_key in SCENARIOS[name]:
        hold(
            people["me"], custom_role(spec), department=departments[dept_key] if dept_key else None
        )
    options = [departments["A"], departments["B"], None]
    users = [people["me"], people["other"], None]
    records = [
        make_record(f"r{n}", d, c, a)
        for n, (d, c, a) in enumerate(itertools.product(options, users, users))
    ]
    if with_record_grant:
        grant(people["me"], records[5])

    expected = {r.title for r in records if can(people["me"], "finance", "VIEW", r)}
    assert visible(people["me"]) == expected
