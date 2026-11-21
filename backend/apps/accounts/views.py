from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import UserSession
from .permissions import IsSignedIn
from .serializers import (
    LoginSerializer,
    PasswordChangeSerializer,
    UserProfileSerializer,
    UserSessionSerializer,
)


def _session_info(request) -> dict:
    session = request.session
    login_at = session.get("login_at")
    absolute = (
        datetime.fromtimestamp(login_at, tz=UTC)
        + timedelta(seconds=settings.TCOS_SESSION_ABSOLUTE_SECONDS)
        if login_at
        else None
    )
    return {
        "idle_expires_at": session.get_expiry_date(),
        "absolute_expires_at": absolute,
    }


def _auth_payload(request) -> dict:
    return {
        "user": UserProfileSerializer(request.user).data,
        "session": _session_info(request),
    }


# The login view has no session yet, so DRF would skip CSRF checking. It is
# enforced explicitly to prevent "login CSRF".
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]  # explicit: signing in is public by definition

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.sign_in(
            request,
            serializer.validated_data["username"],
            serializer.validated_data["password"],
        )
        return Response(_auth_payload(request))


class LogoutView(APIView):
    permission_classes = [IsSignedIn]
    allow_password_change_pending = True

    def post(self, request):
        services.end_current_session(request, UserSession.EndReason.LOGOUT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsSignedIn]
    allow_password_change_pending = True

    def get(self, request):
        return Response(_auth_payload(request))


class SessionListView(APIView):
    permission_classes = [IsSignedIn]
    allow_password_change_pending = True

    def get(self, request):
        sessions = services.list_active_sessions(request.user)
        serializer = UserSessionSerializer(
            sessions, many=True, context={"current_session_key": request.session.session_key}
        )
        return Response({"results": serializer.data})


class SessionDetailView(APIView):
    """End one of the signed-in user's other sessions."""

    permission_classes = [IsSignedIn]
    allow_password_change_pending = True

    def delete(self, request, pk):
        user_session = UserSession.objects.filter(
            pk=pk, user=request.user, ended_at__isnull=True
        ).first()
        if user_session is None:
            raise NotFound()
        if user_session.session_key == request.session.session_key:
            raise ValidationError(
                {"detail": ["This is the session you are using. Use sign out instead."]}
            )
        services.end_session(user_session, UserSession.EndReason.SIGNED_OUT_BY_USER)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EndOtherSessionsView(APIView):
    """'Sign out other devices': ends every session except the current one."""

    permission_classes = [IsSignedIn]
    allow_password_change_pending = True

    def post(self, request):
        ended = services.end_other_sessions(
            request.user, request.session.session_key, UserSession.EndReason.SIGNED_OUT_BY_USER
        )
        return Response({"ended": ended})


class PasswordChangeView(APIView):
    permission_classes = [IsSignedIn]
    allow_password_change_pending = True

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ended = services.change_password(
            request,
            request.user,
            serializer.validated_data["current_password"],
            serializer.validated_data["new_password"],
        )
        return Response({"ended_other_sessions": ended})
