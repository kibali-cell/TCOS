from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organisation.models import Department
from apps.rbac.permissions import RBACPermission, request_access

from . import services


class DashboardPermission(RBACPermission):
    """Any signed-in, active user. What the response contains is decided in ``services``
    from the user's permissions, not here."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if user.must_change_password:
            self.message = "You must change your password before continuing."
            return False
        from apps.accounts import twofactor

        if twofactor.setup_blocked(user):
            self.message = "Set up two-factor sign-in before continuing."
            return False
        return True


class DashboardView(APIView):
    permission_classes = [DashboardPermission]
    rbac_module = "dashboard"

    def get(self, request):
        return Response(services.build_dashboard(request.user))


class DepartmentDashboardView(APIView):
    permission_classes = [DashboardPermission]
    rbac_module = "dashboard"

    def get(self, request, pk):
        department = get_object_or_404(Department.objects.select_related("head"), pk=pk)
        # Out of reach looks the same as missing, so department ids cannot be probed.
        if not services.can_see_department(request.user, request_access(request), department):
            from django.http import Http404

            raise Http404
        return Response(services.build_department_dashboard(request.user, department))
