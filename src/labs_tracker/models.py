"""Compatibility imports; new code should import the owning package."""

from .domain.models import (
    KIND_ISSUE as KIND_ISSUE,
    KIND_PR as KIND_PR,
    KIND_VALUES as KIND_VALUES,
    STATE_OPEN as STATE_OPEN,
    STATE_CLOSED as STATE_CLOSED,
    STATE_VALUES as STATE_VALUES,
    ISSUE_TYPE_VALUES as ISSUE_TYPE_VALUES,
    ISSUE_TYPE_ALIASES as ISSUE_TYPE_ALIASES,
    RESOLUTION_VALUES as RESOLUTION_VALUES,
    RESOLUTION_ALIASES as RESOLUTION_ALIASES,
    normalize_issue_type as normalize_issue_type,
    normalize_resolution as normalize_resolution,
    STATUS_VALUES as STATUS_VALUES,
    HANDLING_STAGE_VALUES as HANDLING_STAGE_VALUES,
    WAIT_REASON_VALUES as WAIT_REASON_VALUES,
    OWNER_VALUES as OWNER_VALUES,
    PRODUCT_VALUES as PRODUCT_VALUES,
    default_repo_manual_fields as default_repo_manual_fields,
    default_issue_manual_fields as default_issue_manual_fields,
)
