"""Journal route registration."""

from __future__ import annotations

from fastapi import APIRouter

from scripts.api.models import JournalPage, JournalRecord
from scripts.api.queries.journals import get_journal, list_journals
from scripts.shared.constants import API_PREFIX

router = APIRouter(prefix=API_PREFIX)

router.add_api_route(
    "/journals",
    list_journals,
    methods=["GET"],
    response_model=JournalPage,
)
router.add_api_route(
    "/journals/{journal_id}",
    get_journal,
    methods=["GET"],
    response_model=JournalRecord,
)
