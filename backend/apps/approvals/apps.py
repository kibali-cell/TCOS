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

        from apps.core import documents

        documents.register_parent("approvals.ApprovalRequest", _attachment_policy())


def _attachment_policy():
    """Who may see, add and remove files on an approval request.

    See: anyone who can see the request. Add: its requester, while it is a draft or open.
    Remove: its requester, only while it is still a draft (once submitted, the files are
    part of what the approvers saw and stay)."""
    from apps.core.documents import ParentPolicy

    from .models import OPEN_STATUSES, ApprovalRequest
    from .services import visible_requests

    def _request(pk):
        return ApprovalRequest.objects.filter(pk=pk).first()

    def can_view(user, pk):
        return visible_requests(user).filter(pk=pk).exists()

    def can_attach(user, pk):
        req = _request(pk)
        return bool(req and req.requester_id == user.pk and req.status in ("DRAFT", *OPEN_STATUSES))

    def can_archive(user, document):
        req = _request(document.parent_id)
        return bool(req and req.requester_id == user.pk and req.status == "DRAFT")

    return ParentPolicy(
        can_view=can_view,
        can_attach=can_attach,
        can_archive=can_archive,
        classifications=("NORMAL", "CONFIDENTIAL"),
        default_classification="CONFIDENTIAL",
        max_files=10,
    )
