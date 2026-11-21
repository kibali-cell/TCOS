from unittest import mock

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_ok_when_database_reachable():
    response = APIClient().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_health_returns_503_without_leaking_details_when_database_down(caplog):
    with mock.patch(
        "apps.core.views.connection.cursor",
        side_effect=OperationalError("connection to server at 10.0.0.5 failed"),
    ):
        response = APIClient().get("/api/v1/health/")
    assert response.status_code == 503
    body = response.json()
    assert body == {"status": "error", "database": "unavailable"}
    # Neither the response nor the server log may contain infrastructure details.
    assert "10.0.0.5" not in response.content.decode()
    assert "10.0.0.5" not in caplog.text
    assert "OperationalError" in caplog.text


def test_health_is_json_only_no_browsable_api():
    response = APIClient().get("/api/v1/health/", HTTP_ACCEPT="text/html")
    assert response["Content-Type"].startswith("application/json")


def test_csrf_endpoint_sets_cookie():
    response = APIClient().get("/api/v1/csrf/")
    assert response.status_code == 200
    assert "csrftoken" in response.cookies
    assert response.cookies["csrftoken"].value
