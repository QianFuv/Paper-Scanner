"""Weekly route registration."""

from __future__ import annotations

from fastapi import APIRouter

from scripts.api.models import WeeklyUpdatesResponse
from scripts.api.queries.weekly import get_weekly_updates
from scripts.shared.constants import API_PREFIX

router = APIRouter(prefix=API_PREFIX)

router.add_api_route(
    "/weekly-updates",
    get_weekly_updates,
    methods=["GET"],
    response_model=WeeklyUpdatesResponse,
)
