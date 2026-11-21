import logging

from django.db import Error as DatabaseError
from django.db import connection
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """Public liveness/readiness probe. Confirms the database is reachable.

    Deliberately returns no version numbers, host names or error details.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]  # explicit: this endpoint is intentionally public

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError as exc:
            # Log the error type only: tracebacks include the database host,
            # port and user, and probes run every few seconds.
            logger.warning("Health check failed: database unavailable (%s)", type(exc).__name__)
            return Response({"status": "error", "database": "unavailable"}, status=503)
        return Response({"status": "ok", "database": "ok"})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Sets the CSRF cookie so the single-page app can send the token back."""

    authentication_classes: list = []
    permission_classes = [AllowAny]  # explicit: needed before login

    def get(self, request):
        return Response({"detail": "CSRF cookie set."})
