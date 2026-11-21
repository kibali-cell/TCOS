"""Shared API conventions: error format and pagination.

Every error response has the same shape::

    {"error": {"code": "...", "message": "...", "details": {...} | null}}

``details`` is only populated for validation errors (field -> messages).
"""

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import exception_handler as drf_exception_handler

_CODES_BY_STATUS = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
}

_GENERIC_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "The request could not be processed.",
    status.HTTP_401_UNAUTHORIZED: "Authentication is required.",
    status.HTTP_403_FORBIDDEN: "You do not have permission to perform this action.",
    status.HTTP_404_NOT_FOUND: "The requested resource was not found.",
}


def exception_handler(exc, context):
    """Wrap DRF's handler so all errors use the project error envelope."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    code = _CODES_BY_STATUS.get(response.status_code, "error")
    details = None

    if isinstance(exc, ValidationError):
        code = "validation_error"
        message = "The submitted data is not valid."
        details = response.data
    else:
        data = response.data
        detail = data.get("detail") if isinstance(data, dict) else None
        message = (
            str(detail)
            if detail
            else _GENERIC_MESSAGES.get(response.status_code, "The request failed.")
        )

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response


class StandardPagination(PageNumberPagination):
    """Default pagination for every list endpoint."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
