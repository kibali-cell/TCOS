"""Tests for the project-wide API conventions: default-deny and error format."""

from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

factory = APIRequestFactory()


class UnconfiguredView(APIView):
    """A view that forgets to declare permissions."""

    def get(self, request):
        return Response({"secret": "should never be returned"})


class ValidationView(APIView):
    permission_classes = []  # open on purpose, this test targets the error format

    def get(self, request):
        class Form(serializers.Serializer):
            name = serializers.CharField()

        form = Form(data={})
        form.is_valid(raise_exception=True)


class MissingView(APIView):
    permission_classes = []

    def get(self, request):
        raise NotFound()


def test_view_without_permission_class_is_denied_by_default():
    response = UnconfiguredView.as_view()(factory.get("/x"))
    assert response.status_code == 403
    assert "secret" not in str(response.data)


def test_validation_errors_use_standard_envelope():
    response = ValidationView.as_view()(factory.get("/x"))
    assert response.status_code == 400
    error = response.data["error"]
    assert error["code"] == "validation_error"
    assert "name" in error["details"]


def test_not_found_uses_standard_envelope():
    response = MissingView.as_view()(factory.get("/x"))
    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"
    assert response.data["error"]["details"] is None


def test_denied_response_uses_standard_envelope():
    response = UnconfiguredView.as_view()(factory.get("/x"))
    assert response.data["error"]["code"] == "permission_denied"
