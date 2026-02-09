"""Issue route registration."""

from __future__ import annotations

from fastapi import APIRouter

from scripts.api.models import IssuePage, IssueRecord
from scripts.api.queries.issues import get_issue, list_issues
from scripts.shared.constants import API_PREFIX

router = APIRouter(prefix=API_PREFIX)

router.add_api_route(
    "/issues",
    list_issues,
    methods=["GET"],
    response_model=IssuePage,
)
router.add_api_route(
    "/issues/{issue_id}",
    get_issue,
    methods=["GET"],
    response_model=IssueRecord,
)
