"""TZS limits: explicit risk tiers, kept as versioned, approved configuration (D-020, D-066).

Nothing here is hidden in code except the first, provisional version. A new version only
becomes active when an approval request for it is approved by someone other than whoever
proposed it (see ``services``), and the screen shows which version is in force and
whether it has been ratified.
"""

from __future__ import annotations

# Kinds of request that are HIGH whatever the amount (D-020).
ALWAYS_HIGH_KINDS = {
    "PAYROLL": "Payroll",
    "STAFF_LOAN": "Staff loans",
    "PAYEE_CHANGE": "Bank or payee changes",
    "ASSET_DISPOSAL": "Asset disposal",
    "WRITE_OFF": "Write-offs",
    "DONOR_REFUND": "Donor refunds",
}

INITIAL_LOW_MAX = 200_000
INITIAL_MEDIUM_MAX = 2_000_000

LIMITS_EXPLANATION = (
    "Risk level is set by the server from the amount in TZS. LOW: up to the first limit. "
    "MEDIUM: above that, up to the second limit. HIGH: above the second limit, and always "
    "for the kinds of request listed as always high. A HIGH request needs the approver to "
    "enter their password again when they decide. These limits only take effect when a "
    "Board Member or the Executive Director, who did not propose them, approves them."
)


def active_policy():
    from .models import TzsLimitPolicy

    return TzsLimitPolicy.objects.filter(state="ACTIVE").first()


def risk_for(amount_tzs: int | None, kind: str = "", policy=None) -> str:
    """LOW, MEDIUM or HIGH. A request with no amount and no special kind is LOW."""
    policy = policy or active_policy()
    if kind and policy and kind in policy.always_high:
        return "HIGH"
    if amount_tzs is None or policy is None:
        return "HIGH" if policy is None and amount_tzs else "LOW"
    if amount_tzs <= policy.low_max:
        return "LOW"
    if amount_tzs <= policy.medium_max:
        return "MEDIUM"
    return "HIGH"
