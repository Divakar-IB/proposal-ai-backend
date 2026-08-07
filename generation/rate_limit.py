"""Groq TPM governance for proposal drafting.

Groq's tokens-per-minute allowance is an **organisation-level** cap shared by
every request the account makes, and it behaves as a continuously-refilling
bucket (the x-ratelimit-reset-tokens header comes back in milliseconds, not as
a minute boundary). Two things follow:

1. The governor is a module-level singleton. A per-run governor would let two
   simultaneous generations each believe it had the whole budget, and both
   would overrun it.
2. The limit is also a hard *per-request* ceiling: Groq rejects any single
   request whose prompt plus reserved completion exceeds it with 413 "Request
   too large". A 413 is a sizing bug, not a pacing one — retrying after a wait
   cannot fix it, so it is surfaced immediately with the knobs named rather
   than burning the retry budget.

429 is the opposite: pacing, always retryable, and Groq tells us exactly how
long to wait in Retry-After. We honour that value rather than inventing a
backoff curve.
"""

import asyncio
import re
from typing import Awaitable, Callable, Mapping, Optional, TypeVar

from openai import APIStatusError, RateLimitError

from config import config
from utilities.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Groq expresses reset windows as "952ms", "1.492s", "1m26.4s".
_DURATION_PATTERN = re.compile(r"(?:(?P<minutes>[\d.]+)m(?![s]))?(?:(?P<seconds>[\d.]+)s)?(?:(?P<millis>[\d.]+)ms)?")

# Never sleep longer than this on a single Retry-After, however large the
# header. A generation is streaming to a client that is holding an open SSE
# connection; a multi-minute silent stall reads as a hang.
MAX_RETRY_WAIT_SECONDS = 65.0

# Floor for a Retry-After wait. Groq occasionally reports a sub-millisecond
# window; sleeping that long just re-issues the request into the same wall.
MIN_RETRY_WAIT_SECONDS = 0.5


def parse_duration(raw: Optional[str]) -> Optional[float]:
    """Groq duration string -> seconds. Returns None if unparseable."""

    if not raw:
        return None
    text = raw.strip()
    try:
        # A bare number in Retry-After is seconds, per the HTTP spec.
        return float(text)
    except ValueError:
        pass

    match = _DURATION_PATTERN.fullmatch(text)
    if not match or not any(match.groupdict().values()):
        return None
    total = 0.0
    if match.group("minutes"):
        total += float(match.group("minutes")) * 60
    if match.group("seconds"):
        total += float(match.group("seconds"))
    if match.group("millis"):
        total += float(match.group("millis")) / 1000
    return total


class TokenGovernor:
    """Tracks remaining TPM headroom from response headers and paces requests.

    The semaphore in generation/graph.py caps how many sections are in flight;
    this caps how many *tokens* are. They are different limits and the token one
    is what actually 429s: two small sections concurrently are fine, two large
    ones are not.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._limit: Optional[int] = None
        self._remaining: Optional[int] = None
        self._reset_seconds: float = 0.0

    @property
    def limit(self) -> int:
        """Observed limit, falling back to the configured value until the first
        response header has been seen. The header is authoritative — an account
        upgraded to a paid tier reports the new limit without a config change."""

        return self._limit if self._limit is not None else config.groq.tokens_per_minute

    @property
    def remaining(self) -> Optional[int]:
        return self._remaining

    @property
    def reset_seconds(self) -> float:
        """Time the last response said the token bucket needs to refill."""

        return self._reset_seconds

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Absorb x-ratelimit-* state from a completed response."""

        if not headers:
            return

        limit = headers.get("x-ratelimit-limit-tokens")
        if limit and limit.isdigit():
            observed = int(limit)
            if observed != self._limit:
                logger.info("groq token limit observed | limit=%s (config=%s)", observed, config.groq.tokens_per_minute)
            self._limit = observed

        remaining = headers.get("x-ratelimit-remaining-tokens")
        if remaining and remaining.isdigit():
            self._remaining = int(remaining)

        reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
        if reset is not None:
            self._reset_seconds = reset

    async def acquire(self, estimated_tokens: int, label: str) -> None:
        """Pre-flight check: wait if the last response said headroom is too thin
        for a request this size.

        Deliberately optimistic on the first call of a process — with no header
        seen yet we let the request through and learn the real numbers from its
        response, rather than stalling on a guess.

        Held under a lock so two concurrent sections cannot both read the same
        stale `remaining` and both decide there is room.
        """

        needed = int(estimated_tokens * max(config.generation.tpm_headroom_ratio, 0.0))
        async with self._lock:
            if self._remaining is None or needed <= 0:
                return
            if self._remaining >= needed:
                # Debit locally so a concurrent section sees the reservation
                # before this request's own response header arrives.
                self._remaining -= needed
                return

            wait = min(max(self._reset_seconds, MIN_RETRY_WAIT_SECONDS), MAX_RETRY_WAIT_SECONDS)
            logger.info(
                "throttling section on TPM headroom | section=%s needed=%s remaining=%s waiting=%.2fs",
                label,
                needed,
                self._remaining,
                wait,
            )
            await asyncio.sleep(wait)
            # The bucket refills over the reset window; assume full and let the
            # response headers correct us.
            self._remaining = self.limit - needed


# Module-level: the TPM cap is account-wide, so all generations share this.
governor = TokenGovernor()


def _retry_after_seconds(error: Exception) -> Optional[float]:
    """Exact wait Groq asked for, from the header or the error body."""

    response = getattr(error, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None) or {}
        for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            parsed = parse_duration(headers.get(header))
            if parsed:
                return parsed

    # Fallback: "Please try again in 2.34s" in the message body.
    match = re.search(r"try again in ([\d.]+(?:ms|s|m[\d.]*s?))", str(error))
    if match:
        return parse_duration(match.group(1))
    return None


class RequestTooLargeError(RuntimeError):
    """413 from Groq — the request itself exceeds the per-request TPM ceiling.

    Separate from a rate-limit error because the remedy is different: waiting
    achieves nothing, the request has to be made smaller.
    """


async def run_with_rate_limit_retry(
    operation: Callable[[], Awaitable[T]],
    label: str,
    max_attempts: Optional[int] = None,
) -> T:
    """Runs `operation`, retrying only it on 429 for exactly as long as Groq asks.

    Scoped to one section, so a rate-limited section never fails the other
    eleven. `operation` must be re-runnable from scratch: a 429 on a streaming
    request is raised at connection time, before any delta has been yielded, so
    a retry restarts cleanly rather than resuming mid-section.
    """

    attempts = max_attempts if max_attempts is not None else config.generation.max_rate_limit_retries
    attempts = max(attempts, 1)
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except RateLimitError as error:
            last_error = error
            wait = _retry_after_seconds(error)
            if wait is None:
                # No guidance from Groq — fall back to the observed reset window.
                wait = max(governor.reset_seconds, MIN_RETRY_WAIT_SECONDS)
            wait = min(max(wait, MIN_RETRY_WAIT_SECONDS), MAX_RETRY_WAIT_SECONDS)
            if attempt == attempts:
                break
            logger.warning(
                "groq 429 | section=%s attempt=%s/%s waiting=%.2fs (Retry-After)",
                label,
                attempt,
                attempts,
                wait,
            )
            await asyncio.sleep(wait)
        except APIStatusError as error:
            if error.status_code == 413:
                # Not retryable by waiting — report it with the levers named.
                raise RequestTooLargeError(
                    f"section {label!r} exceeds Groq's per-request token ceiling "
                    f"(limit={governor.limit} tokens/min). Lower the proposal's page_count, "
                    f"reduce generation.TOP_K_SECTION_CHUNKS, or raise groq.tokens_per_minute "
                    f"if the account tier allows it. Original error: {error}"
                ) from error
            raise

    raise RuntimeError(f"section {label!r} still rate-limited after {attempts} attempts: {last_error}")
