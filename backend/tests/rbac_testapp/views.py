"""Reference implementation of a module view using the central engine.

Future module views follow this pattern: declare `rbac_module`, scope the queryset, and
re-check the record's new state on writes.
"""

from rest_framework import serializers, viewsets

from apps.rbac.permissions import RBACPermission, ScopedQuerysetMixin, ScopedWriteMixin

from .models import Record


class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = Record
        fields = ["id", "title", "department", "assigned_to"]


class RecordViewSet(ScopedQuerysetMixin, ScopedWriteMixin, viewsets.ModelViewSet):
    queryset = Record.objects.all()
    serializer_class = RecordSerializer
    permission_classes = [RBACPermission]
    rbac_module = "finance"


class StoreRecordViewSet(RecordViewSet):
    """The same records under a NON-sensitive module (stores), so tests can assign roles
    for it directly. Roles that reach finance data need an approval (D-044)."""

    rbac_module = "stores"
