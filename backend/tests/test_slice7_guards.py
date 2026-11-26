"""Guards added in Slice 7 around accounts whose password is still a temporary one."""

import pytest
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.rbac import services as rbac
from apps.rbac.models import Role
from tests.test_settings import _prod_env, _run

pytestmark = pytest.mark.django_db


def test_sensitive_access_cannot_be_attached_to_an_account_with_a_temporary_password(make_user):
    admin, requester, approver = make_user("adm"), make_user("req"), make_user("app")
    newcomer = make_user("new")
    User.objects.filter(pk=newcomer.pk).update(must_change_password=True)
    newcomer.refresh_from_db()
    role = Role.objects.get(code="FINANCE_OFFICER")
    with pytest.raises(PermissionDenied) as caught:
        rbac.assign_role_approved(requester, approver, newcomer, role, request_number="REQ-1")
    assert "password_not_set" in str(caught.value.get_codes())
    assert not newcomer.user_roles.exists()
    # Ordinary roles are fine: onboarding is not blocked.
    rbac.assign_role(admin, newcomer, Role.objects.get(code="STOREKEEPER"))
    # Once the person has set their own password, the same grant goes through.
    User.objects.filter(pk=newcomer.pk).update(must_change_password=False)
    newcomer.refresh_from_db()
    rbac.assign_role_approved(requester, approver, newcomer, role, request_number="REQ-1")
    assert newcomer.user_roles.filter(role=role).exists()


def test_production_refuses_to_start_without_the_encryption_key():
    env = _prod_env()
    env["TCOS_ENCRYPTION_KEY"] = ""
    result = _run(["manage.py", "check"], env)
    assert result.returncode != 0
    assert "TCOS_ENCRYPTION_KEY" in result.stderr


def test_production_refuses_a_short_encryption_key():
    env = _prod_env()
    env["TCOS_ENCRYPTION_KEY"] = "short"
    result = _run(["manage.py", "check"], env)
    assert result.returncode != 0


def test_a_stored_secret_does_not_decrypt_for_another_user_or_with_a_changed_value():
    from apps.core import crypto

    sealed = crypto.encrypt("JBSWY3DPEHPK3PXP", "2fa:1")
    assert crypto.decrypt(sealed, "2fa:1") == "JBSWY3DPEHPK3PXP"
    assert "JBSWY3DPEHPK3PXP" not in sealed
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(sealed, "2fa:2")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(sealed[:-4] + "AAAA", "2fa:1")
    assert crypto.encrypt("x", "c") != crypto.encrypt("x", "c")  # fresh nonce each time
