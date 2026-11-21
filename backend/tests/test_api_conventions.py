"""Tests for the project-wide API conventions: default-deny and error format."""

from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
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
    """Anonymous callers get 401 and never see the view's data."""
    response = UnconfiguredView.as_view()(factory.get("/x"))
    assert response.status_code == 401
    assert "secret" not in str(response.data)


def test_signed_in_user_is_still_denied_by_default(make_user):
    request = factory.get("/x")
    force_authenticate(request, user=make_user())
    response = UnconfiguredView.as_view()(request)
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


def test_denied_responses_use_standard_envelope(make_user):
    anonymous = UnconfiguredView.as_view()(factory.get("/x"))
    assert anonymous.data["error"]["code"] == "not_authenticated"

    request = factory.get("/x")
    force_authenticate(request, user=make_user())
    signed_in = UnconfiguredView.as_view()(request)
    assert signed_in.data["error"]["code"] == "permission_denied"
