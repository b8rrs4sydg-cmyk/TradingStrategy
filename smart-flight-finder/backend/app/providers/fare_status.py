"""Why a fare query has no price — the states a lookup can end in, and when each may be asked again.

``NO_RESULT`` is the only answer that means "no flight"; timeouts, blocks and parse errors are failures and must never be
stored as unavailable (that hides possibly cheaper plans). ``NOT_QUERIED`` means the budget ran out.
"""

from __future__ import annotations

from enum import StrEnum


class FareStatus(StrEnum):
    FOUND = "found"
    NO_RESULT = "no_result"
    NOT_QUERIED = "not_queried"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    PARSE_ERROR = "parse_error"


# seconds before the same query may be asked again (None: no wait)
RETRY_AFTER_S: dict[FareStatus, int | None] = {
    FareStatus.FOUND: 6 * 3600,
    FareStatus.NO_RESULT: 3 * 3600,
    FareStatus.NOT_QUERIED: None,
    FareStatus.TIMEOUT: 120,
    FareStatus.BLOCKED: 1800,
    FareStatus.PARSE_ERROR: 900,
}


def retry_after(status: FareStatus, attempts: int = 1) -> int:
    """Wait for ``status`` after ``attempts`` tries in a row; failures back off exponentially (capped at 8x)."""

    base = RETRY_AFTER_S[status] or 0
    if status in (FareStatus.TIMEOUT, FareStatus.BLOCKED, FareStatus.PARSE_ERROR):
        return base * min(2 ** max(0, attempts - 1), 8)
    return base


def is_failure(status: FareStatus) -> bool:
    return status in (FareStatus.TIMEOUT, FareStatus.BLOCKED, FareStatus.PARSE_ERROR)


def may_mark_unavailable(status: FareStatus) -> bool:
    """Only a confirmed 'no result' may land in ``unavailable`` / ``missing``."""

    return status is FareStatus.NO_RESULT
