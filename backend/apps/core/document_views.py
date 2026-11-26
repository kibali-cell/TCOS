"""Document API. Access is decided by the record a file is attached to (``documents``)."""

from django.http import FileResponse
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rbac.permissions import RBACPermission

from . import documents


class DocumentPermission(RBACPermission):
    """Any signed-in, active user who is not blocked by a password change or two-factor set-up.
    Whether they may touch a given file is decided by the record it belongs to."""

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


class _Base(APIView):
    permission_classes = [DocumentPermission]
    rbac_module = "documents"


class UploadSerializer(serializers.Serializer):
    parent_type = serializers.CharField(max_length=60)
    parent_id = serializers.UUIDField()
    file = serializers.FileField()
    classification = serializers.CharField(max_length=16, required=False, allow_blank=True)


class DocumentListView(_Base):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        parent_type = request.query_params.get("parent_type", "")
        try:
            parent_id = serializers.UUIDField().run_validation(
                request.query_params.get("parent_id")
            )
        except serializers.ValidationError as exc:
            raise NotFound() from exc
        rows = documents.list_for(request.user, parent_type, parent_id)
        return Response({"results": [documents.payload(d, request.user) for d in rows]})

    def post(self, request):
        data = UploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        document = documents.upload(
            request.user,
            data.validated_data["parent_type"],
            data.validated_data["parent_id"],
            data.validated_data["file"],
            data.validated_data.get("classification", ""),
        )
        return Response(documents.payload(document, request.user), status=status.HTTP_201_CREATED)


class DocumentDownloadView(_Base):
    def get(self, request, pk):
        document, handle = documents.get_for_download(request.user, pk)
        response = FileResponse(
            handle,
            as_attachment=True,
            filename=document.original_name,
            content_type=document.content_type,
        )
        # Never shown inline, never sniffed, never kept by a shared cache.
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


class DocumentArchiveView(_Base):
    def post(self, request, pk):
        document = documents.archive(request.user, pk)
        return Response(documents.payload(document, request.user))
