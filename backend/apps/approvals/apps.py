from django.apps import AppConfig


class ApprovalsConfig(AppConfig):
    name = "apps.approvals"
    label = "approvals"
    verbose_name = "Approval Centre"

    def ready(self):
        from apps.organisation import services as organisation

        from .services import open_requests_blocker

        if open_requests_blocker not in organisation.ARCHIVE_BLOCKERS:
            organisation.ARCHIVE_BLOCKERS.append(open_requests_blocker)
