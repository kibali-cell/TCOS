import time

from django.conf import settings

from . import services
from .models import UserSession


class SessionPolicyMiddleware:
    """Enforces the absolute session length and records last activity.

    The idle timeout is handled by Django's session expiry (SESSION_COOKIE_AGE
    with SESSION_SAVE_EVERY_REQUEST). Sessions that were not created through
    TCOS sign-in (no ``login_at``) are rejected.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            self._enforce(request)
        return self.get_response(request)

    @staticmethod
    def _enforce(request):
        now = int(time.time())
        login_at = request.session.get("login_at")
        if login_at is None or now - login_at > settings.TCOS_SESSION_ABSOLUTE_SECONDS:
            services.end_current_session(request, UserSession.EndReason.ABSOLUTE_TIMEOUT)
            return
        if now - request.session.get("seen_at", 0) >= services.SEEN_UPDATE_SECONDS:
            request.session["seen_at"] = now
            services.touch_session(request.session.session_key)
