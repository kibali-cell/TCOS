from rest_framework.authentication import SessionAuthentication


class TcosSessionAuthentication(SessionAuthentication):
    """Session authentication that answers 401 (not 403) when not signed in.

    CSRF is enforced for every authenticated request, as in SessionAuthentication.
    """

    def authenticate_header(self, request):
        return "Session"
