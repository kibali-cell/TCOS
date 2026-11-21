"""Core permission classes.

Slice 2 introduces the central RBAC engine (``apps.rbac.permissions``) which
replaces ``DenyByDefault`` as the project-wide default.
"""

from rest_framework.permissions import BasePermission


class DenyByDefault(BasePermission):
    """Project-wide default: deny everything unless a view opts in explicitly.

    A view that forgets to declare permissions therefore fails closed instead
    of silently exposing data.
    """

    message = "This endpoint has no permission policy configured."

    def has_permission(self, request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False
