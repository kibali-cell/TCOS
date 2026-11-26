from . import context


class RequestContextMiddleware:
    """Gives every request an id, returned as ``X-Request-ID`` and stored on audit events."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.accounts.services import get_client_ip  # late import: avoid a cycle

        request_id = context.new_request_id(request.META.get("HTTP_X_REQUEST_ID"))
        request.request_id = request_id
        token = context.set_context(
            {
                "request_id": request_id,
                "ip_address": get_client_ip(request),
                "user_agent": (request.META.get("HTTP_USER_AGENT", "") or "")[:400],
            }
        )
        try:
            response = self.get_response(request)
        finally:
            context.reset_context(token)
        response["X-Request-ID"] = request_id
        return response
