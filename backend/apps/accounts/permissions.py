from rest_framework.permissions import BasePermission


class IsSignedIn(BasePermission):
    """Signed-in, active user.

    While ``must_change_password`` is set, only views that opt in with
    ``allow_password_change_pending = True`` (profile, logout, change password)
    are reachable.
    """

    message = "You must change your password before continuing."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if user.must_change_password and not getattr(view, "allow_password_change_pending", False):
            return False
        if not getattr(view, "allow_password_change_pending", False):
            from . import twofactor

            if twofactor.setup_blocked(user):
                self.message = "Set up two-factor sign-in before continuing."
                return False
        return True
