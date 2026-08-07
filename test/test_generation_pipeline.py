"""The generation pipeline itself — the one module that drives the real
LangGraph run rather than a router.

`test_proposals.py` stubs `generate_proposal_stream` wholesale to test the
endpoint's SSE plumbing, so nothing else exercises `generation/graph.py`,
`section_runner.py`, `token_budget.py` or `rate_limit.py`. These tests pin the
two failure modes that were previously silent:

* a response that spent its whole token allowance on reasoning and emitted no
  body text, which used to be persisted as a finished-but-empty section;
* a response cut off by the token cap, which used to be persisted as if
  complete.

and the bounded-concurrency behaviour layered on top of them.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from httpx import Headers

from config import config
from database.db_enum import GenerationMode, ProposalSectionStatus, ProposalStatus
from generation import rate_limit
from generation.nodes import (
    EmptySectionError,
    TruncatedSectionError,
    validate_section_outcome,
)
from generation.rate_limit import (
    RequestTooLargeError,
    TokenGovernor,
    parse_duration,
    run_with_rate_limit_retry,
)
from generation.sections import SECTION_DEFINITIONS
from generation.token_budget import (
    MIN_COMPLETION_TOKENS,
    clamp_completion_tokens,
    completion_tokens_for,
    estimate_prompt_tokens,
    max_request_tokens,
    prompt_exceeds_ceiling,
)
from llm.chat_client import GroqChatClient, StreamOutcome

# ==================================================================
# Token budgeting
# ==================================================================


def test_completion_cap_scales_with_the_word_target():
    small = completion_tokens_for(163)
    large = completion_tokens_for(1961)
    assert small < large
    # Enough room for the words themselves plus a reasoning preamble.
    assert large > int(1961 * 1.3)


def test_completion_cap_has_a_floor():
    """A 60-word MIN_SECTION_WORDS section still needs room to think before it
    writes, or it reproduces the empty-section bug at the small end.

    In practice COMPLETION_HEADROOM_TOKENS alone clears MIN_COMPLETION_TOKENS,
    so this asserts the property (never below the floor) rather than equality —
    the `max()` in completion_tokens_for is a guard for anyone who lowers the
    headroom later, not a branch reached today.
    """

    assert completion_tokens_for(0) >= MIN_COMPLETION_TOKENS
    assert completion_tokens_for(60) >= MIN_COMPLETION_TOKENS


def test_clamp_is_a_no_op_when_the_request_fits():
    granted, was_clamped = clamp_completion_tokens(1000, 2000)
    assert (granted, was_clamped) == (2000, False)


def test_clamp_keeps_the_largest_section_under_the_per_request_ceiling():
    """The reason this module exists: `proposed_solution` at 20 pages wants more
    than a single free-tier request may occupy, and an unclamped request is a
    hard 413 rather than a short section."""

    prompt_tokens = 5437
    desired = completion_tokens_for(1961)
    assert prompt_tokens + desired > max_request_tokens()

    granted, was_clamped = clamp_completion_tokens(prompt_tokens, desired)

    assert was_clamped is True
    assert granted < desired
    assert prompt_tokens + granted <= max_request_tokens()


def test_clamp_never_grants_zero_even_when_the_prompt_alone_overflows():
    granted, was_clamped = clamp_completion_tokens(max_request_tokens() + 5000, 2000)
    assert was_clamped is True
    assert granted == MIN_COMPLETION_TOKENS


def test_clamp_keeps_the_whole_request_legal_whenever_the_prompt_leaves_room():
    """The clamp's actual contract. It cannot help when the prompt alone fills
    the ceiling — that case is reported by `prompt_exceeds_ceiling` instead of
    being silently mis-sized."""

    ceiling = max_request_tokens()
    for prompt_tokens in (100, 777, 3000, 5437, ceiling - MIN_COMPLETION_TOKENS):
        granted, _ = clamp_completion_tokens(prompt_tokens, 4000)
        assert not prompt_exceeds_ceiling(prompt_tokens)
        assert prompt_tokens + granted <= ceiling


def test_prompt_exceeds_ceiling_identifies_the_unfixable_case():
    ceiling = max_request_tokens()
    assert prompt_exceeds_ceiling(ceiling) is True
    assert prompt_exceeds_ceiling(ceiling - MIN_COMPLETION_TOKENS) is False


def test_prompt_estimate_grows_with_content():
    small = estimate_prompt_tokens([{"role": "user", "content": "hello"}])
    large = estimate_prompt_tokens([{"role": "user", "content": "hello " * 500}])
    assert 0 < small < large


def test_prompt_estimate_tolerates_missing_content():
    assert estimate_prompt_tokens([{"role": "user"}, {"role": "user", "content": None}]) > 0


# ==================================================================
# Rate limiting
# ==================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("952ms", 0.952),
        ("1.492s", 1.492),
        ("2", 2.0),
        ("1m26.4s", 86.4),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_duration_handles_groq_formats(raw, expected):
    result = parse_duration(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected, abs=0.01)


def test_governor_learns_the_real_limit_from_headers():
    """The header wins over config, so upgrading the account tier needs no code
    or config change."""

    governor = TokenGovernor()
    assert governor.limit == config.groq.tokens_per_minute

    governor.update_from_headers(
        Headers(
            {
                "x-ratelimit-limit-tokens": "300000",
                "x-ratelimit-remaining-tokens": "298000",
                "x-ratelimit-reset-tokens": "1.2s",
            }
        )
    )

    assert governor.limit == 300000
    assert governor.remaining == 298000
    assert governor.reset_seconds == pytest.approx(1.2)


def test_governor_ignores_junk_headers():
    governor = TokenGovernor()
    governor.update_from_headers(Headers({"x-ratelimit-remaining-tokens": "not-a-number"}))
    assert governor.remaining is None


async def test_governor_lets_the_first_request_through():
    """With no header seen yet there is nothing to pace against; stalling on a
    guess would delay every generation's first section."""

    governor = TokenGovernor()
    await asyncio.wait_for(governor.acquire(7000, "Executive Summary"), timeout=1)


async def test_governor_debits_locally_so_concurrent_sections_see_the_reservation():
    governor = TokenGovernor()
    governor.update_from_headers(Headers({"x-ratelimit-remaining-tokens": "8000"}))

    await governor.acquire(3000, "one")

    assert governor.remaining == 5000


async def test_governor_waits_when_headroom_is_thin(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(rate_limit.asyncio, "sleep", fake_sleep)

    governor = TokenGovernor()
    governor.update_from_headers(Headers({"x-ratelimit-remaining-tokens": "200", "x-ratelimit-reset-tokens": "1.5s"}))

    await governor.acquire(7000, "Proposed Solution")

    assert slept == [pytest.approx(1.5)]


class FakeRateLimitError(rate_limit.RateLimitError):
    """RateLimitError needs a real response to construct; this carries just the
    header the retry path reads."""

    def __init__(self, retry_after: str):
        self.response = type("R", (), {"headers": Headers({"retry-after": retry_after})})()
        Exception.__init__(self, f"429 rate limit, retry after {retry_after}")


async def test_retry_waits_exactly_what_groq_asked_for(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(rate_limit.asyncio, "sleep", fake_sleep)

    attempts = {"n": 0}

    async def operation():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise FakeRateLimitError("2.5s")
        return "drafted"

    result = await run_with_rate_limit_retry(operation, label="Technology Stack")

    assert result == "drafted"
    assert attempts["n"] == 2
    # The exact Retry-After, not a backoff curve of our own invention.
    assert slept == [pytest.approx(2.5)]


async def test_retry_gives_up_after_the_configured_attempts(monkeypatch):
    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(rate_limit.asyncio, "sleep", fake_sleep)

    attempts = {"n": 0}

    async def operation():
        attempts["n"] += 1
        raise FakeRateLimitError("1s")

    with pytest.raises(RuntimeError, match="still rate-limited"):
        await run_with_rate_limit_retry(operation, label="Company Profile", max_attempts=3)

    assert attempts["n"] == 3


async def test_413_is_not_retried_and_names_the_knobs():
    """A 413 means the request itself is too big for the TPM ceiling. Waiting
    cannot help, so it must not consume the retry budget."""

    attempts = {"n": 0}

    # APIStatusError reaches through to response.request, so the stand-in needs
    # one as well as a status code.
    fake_response = type(
        "R",
        (),
        {"status_code": 413, "headers": Headers({}), "request": object()},
    )()

    async def operation():
        attempts["n"] += 1
        raise rate_limit.APIStatusError("Request too large", response=fake_response, body=None)

    with pytest.raises(RequestTooLargeError) as excinfo:
        await run_with_rate_limit_retry(operation, label="Proposed Solution")

    assert attempts["n"] == 1
    message = str(excinfo.value)
    assert "page_count" in message
    assert "tokens_per_minute" in message


# ==================================================================
# Section validation — the previously-silent failures
# ==================================================================


def test_empty_content_raises_and_names_reasoning_effort():
    """The whole point: nothing in an empty stream hints at the cause, so the
    error has to say it."""

    outcome = StreamOutcome(finish_reason="length", reasoning_chars=1200)

    with pytest.raises(EmptySectionError) as excinfo:
        validate_section_outcome("Proposed Solution", "", outcome, 2549)

    message = str(excinfo.value)
    assert "reasoning_effort" in message
    assert "Proposed Solution" in message


def test_whitespace_only_content_counts_as_empty():
    outcome = StreamOutcome(finish_reason="stop", content_chars=3)
    with pytest.raises(EmptySectionError):
        validate_section_outcome("Company Profile", "   \n\n ", outcome, 500)


def test_truncated_content_raises_even_though_text_arrived():
    outcome = StreamOutcome(finish_reason="length", content_chars=900, reasoning_chars=40)

    with pytest.raises(TruncatedSectionError) as excinfo:
        validate_section_outcome("Security & Data Privacy Framework", "Half a section", outcome, 588)

    assert "cut off" in str(excinfo.value)


def test_absent_finish_reason_is_treated_as_truncation():
    """A stream that ends with no terminal chunk is a dropped tail, not a clean
    finish."""

    outcome = StreamOutcome(finish_reason=None, content_chars=100)
    with pytest.raises(TruncatedSectionError):
        validate_section_outcome("Executive Summary", "Some text", outcome, 327)


def test_clean_completion_passes():
    outcome = StreamOutcome(finish_reason="stop", content_chars=1200, reasoning_chars=25)
    validate_section_outcome("Executive Summary", "A complete section body.", outcome, 327)


# ==================================================================
# StreamOutcome bookkeeping
# ==================================================================


class FakeDelta:
    def __init__(self, content=None, reasoning=None):
        self.content = content
        self.model_extra = {"reasoning": reasoning} if reasoning else {}


class FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class FakeChunk:
    def __init__(self, delta=None, finish_reason=None, choices=None):
        self.choices = choices if choices is not None else [FakeChoice(delta, finish_reason)]


class FakeStream:
    """Stands in for the SDK's Stream: iterable, and carries `response` so the
    rate-limit headers can be read off it."""

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.response = type("R", (), {"headers": Headers(headers or {})})()

    def __iter__(self):
        return iter(self._chunks)


@pytest.fixture
def captured_request(monkeypatch):
    """Replaces the SDK transport so stream_complete's own logic still runs."""

    captured: dict = {}

    def make_client(chunks, headers=None):
        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return FakeStream(chunks, headers)

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

            def with_options(self, **kwargs):
                captured["_with_options"] = kwargs
                return self

        monkeypatch.setattr(GroqChatClient, "get_client", classmethod(lambda cls: FakeClient()))
        return captured

    return make_client


def test_stream_outcome_separates_reasoning_from_content(captured_request):
    captured_request(
        [
            FakeChunk(FakeDelta(reasoning="thinking hard")),
            FakeChunk(FakeDelta(content="Hello ")),
            FakeChunk(FakeDelta(content="world")),
            FakeChunk(FakeDelta(), finish_reason="stop"),
        ],
        headers={"x-ratelimit-remaining-tokens": "7500"},
    )

    outcome = StreamOutcome()
    text = "".join(GroqChatClient.stream_complete([{"role": "user", "content": "x"}], outcome=outcome))

    assert text == "Hello world"
    assert outcome.content_chunks == 2
    assert outcome.reasoning_chars == len("thinking hard")
    assert outcome.finish_reason == "stop"
    assert outcome.truncated is False
    assert outcome.rate_limit_headers["x-ratelimit-remaining-tokens"] == "7500"


def test_stream_outcome_flags_the_all_reasoning_no_content_case(captured_request):
    """The exact production failure, reproduced: reasoning fills the allowance
    and not a single content delta arrives."""

    captured_request(
        [
            FakeChunk(FakeDelta(reasoning="x" * 300)),
            FakeChunk(FakeDelta(), finish_reason="length"),
        ]
    )

    outcome = StreamOutcome()
    text = "".join(GroqChatClient.stream_complete([{"role": "user", "content": "x"}], outcome=outcome))

    assert text == ""
    assert outcome.produced_no_content is True
    assert outcome.truncated is True
    assert outcome.reasoning_chars == 300


def test_stream_skips_usage_only_trailing_chunks(captured_request):
    """Groq's usage trailer has `choices: []`; indexing choices[0] on it is an
    IndexError that would kill the section."""

    captured_request(
        [
            FakeChunk(FakeDelta(content="body")),
            FakeChunk(choices=[]),
            FakeChunk(FakeDelta(), finish_reason="stop"),
        ]
    )

    outcome = StreamOutcome()
    text = "".join(GroqChatClient.stream_complete([{"role": "user", "content": "x"}], outcome=outcome))

    assert text == "body"
    assert outcome.empty_choice_chunks == 1


def test_new_request_params_are_omitted_when_unset(captured_request):
    """Every non-generation caller must send byte-identical requests to before."""

    captured = captured_request([FakeChunk(FakeDelta(content="hi"), finish_reason="stop")])

    list(GroqChatClient.stream_complete([{"role": "user", "content": "x"}]))

    assert "max_completion_tokens" not in captured
    assert "reasoning_effort" not in captured
    assert captured["temperature"] == 0.4
    assert captured["stream"] is True
    assert "tools" not in captured


def test_request_params_are_sent_when_set(captured_request):
    captured = captured_request([FakeChunk(FakeDelta(content="hi"), finish_reason="stop")])

    list(
        GroqChatClient.stream_complete(
            [{"role": "user", "content": "x"}],
            max_completion_tokens=1234,
            reasoning_effort="low",
            max_retries=0,
        )
    )

    assert captured["max_completion_tokens"] == 1234
    assert captured["reasoning_effort"] == "low"
    assert captured["_with_options"] == {"max_retries": 0}


# ==================================================================
# End-to-end pipeline through the real graph
# ==================================================================


class DraftRecorder:
    """Fake `stream_complete` that answers any section and records the calls.

    Deliberately populates `outcome` the way the real client does — the
    validation step is part of what these tests are covering, so a fake that
    left `finish_reason` unset would fail every section as truncated.
    """

    def __init__(self, body_words=40, finish_reason="stop", fail_for=None, delay=0.0):
        self.calls: list[dict] = []
        self.body_words = body_words
        self.finish_reason = finish_reason
        self.fail_for = fail_for or set()
        self.delay = delay
        self.concurrent = 0
        self.max_concurrent = 0

    def __call__(
        self,
        messages,
        temperature=0.4,
        max_completion_tokens=None,
        reasoning_effort=None,
        outcome=None,
        max_retries=None,
    ):
        prompt = messages[-1]["content"]
        title = prompt.split("\n")[1].strip()

        self.calls.append(
            {
                "title": title,
                "max_completion_tokens": max_completion_tokens,
                "reasoning_effort": reasoning_effort,
                "temperature": temperature,
                "max_retries": max_retries,
            }
        )

        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if title in self.fail_for:
                # Reproduces the all-reasoning-no-content response.
                if outcome is not None:
                    outcome.finish_reason = "length"
                    outcome.reasoning_chars = 4538
                    outcome.rate_limit_headers = {"x-ratelimit-remaining-tokens": "6000"}
                return

            body = f"Body of {title}. " + " ".join(["word"] * self.body_words)
            for piece in body.split(" "):
                if self.delay:
                    import time

                    time.sleep(self.delay)
                if outcome is not None:
                    outcome.content_chunks += 1
                    outcome.content_chars += len(piece) + 1
                yield piece + " "

            if outcome is not None:
                outcome.finish_reason = self.finish_reason
                outcome.reasoning_chars = 25
                outcome.rate_limit_headers = {
                    "x-ratelimit-limit-tokens": "8000",
                    "x-ratelimit-remaining-tokens": "6000",
                    "x-ratelimit-reset-tokens": "1s",
                }
        finally:
            self.concurrent -= 1


@pytest.fixture
def recorder(monkeypatch):
    """Patched on GroqChatClient because generation/nodes.py calls it through
    the class, so the class attribute is what the call resolves."""

    instance = DraftRecorder()
    monkeypatch.setattr(GroqChatClient, "stream_complete", instance)
    # Fresh governor per test: the real one is a module-level singleton, and
    # leaked state from one test would pace another.
    monkeypatch.setattr(rate_limit, "governor", TokenGovernor())
    import generation.section_runner as section_runner

    monkeypatch.setattr(section_runner, "governor", rate_limit.governor)
    return instance


async def _run_generation(proposal_id, page_count=5, mode=GenerationMode.LLM_ONLY):
    from generation.proposal_generator import generate_proposal_stream

    events = []
    async for line in generate_proposal_stream(proposal_id, page_count, mode):
        event = line.split("event: ", 1)[1].split("\n", 1)[0]
        data = json.loads(line.split("data: ", 1)[1].strip())
        events.append((event, data))
    return events


@pytest.fixture
def serialized_db_sessions(monkeypatch):
    """Serializes the pipeline's DB critical sections — a test-fixture
    constraint, not a pipeline one.

    conftest pins every session to a single SQLite ``:memory:`` connection via
    ``StaticPool`` (that is what makes an in-memory DB visible across sessions
    at all). Two concurrent transactions on one connection fail with "cannot
    commit transaction - SQL statements in progress". Production is Postgres
    with pool_size=10 / max_overflow=20, so each concurrent section's
    ``db_session()`` gets its own connection, and ``proposal_sections`` has no
    unique constraint for concurrent inserts to contend over.

    Only the DB blocks are serialized, so drafting still genuinely overlaps and
    the concurrency assertions remain meaningful.
    """

    import generation.section_runner as section_runner

    real_db_session = section_runner.db_session
    lock = asyncio.Lock()

    @asynccontextmanager
    async def locked_db_session():
        async with lock:
            async with real_db_session() as session:
                yield session

    monkeypatch.setattr(section_runner, "db_session", locked_db_session)


@pytest.fixture
async def generation_proposal(factory, member, app):
    """`app` is requested so database.SessionLocal points at the test engine —
    the graph opens its own sessions via db_session()."""

    proposal = await factory.proposal(user=member, title="Concurrency Proposal")
    await factory.requirement_document(
        user=member,
        proposal=proposal,
        parsed_data={"project_title": "Trade Data Platform", "scope": "Build it"},
    )
    return proposal


async def test_every_section_is_drafted_once_and_persisted(generation_proposal, recorder, db):
    from sqlalchemy import select

    from database.models import ProposalSection

    events = await _run_generation(generation_proposal.id)

    assert len(recorder.calls) == len(SECTION_DEFINITIONS)
    assert [call["title"] for call in recorder.calls].count("Executive Summary") == 1

    rows = (
        (await db.execute(select(ProposalSection).where(ProposalSection.proposal_id == generation_proposal.id)))
        .scalars()
        .all()
    )
    assert len(rows) == len(SECTION_DEFINITIONS)
    assert {row.order_index for row in rows} == set(range(len(SECTION_DEFINITIONS)))
    assert all(row.content.strip() for row in rows)
    assert all(row.status == ProposalSectionStatus.APPROVED for row in rows)
    assert events[-1][0] == "done"


async def test_one_llm_call_per_section_no_batching(generation_proposal, recorder):
    await _run_generation(generation_proposal.id)

    titles = [call["title"] for call in recorder.calls]
    assert len(titles) == len(titles and set(titles)) == len(SECTION_DEFINITIONS)


async def test_every_request_caps_completion_tokens_and_sets_low_effort(generation_proposal, recorder):
    await _run_generation(generation_proposal.id)

    assert all(call["max_completion_tokens"] > 0 for call in recorder.calls)
    assert all(call["reasoning_effort"] == "low" for call in recorder.calls)
    # Unchanged from before this work.
    assert all(call["temperature"] == 0.4 for call in recorder.calls)
    # The SDK's own retries are off; rate_limit.py owns retrying.
    assert all(call["max_retries"] == 0 for call in recorder.calls)


async def test_bigger_sections_get_bigger_caps(generation_proposal, recorder):
    await _run_generation(generation_proposal.id, page_count=20)

    caps = {call["title"]: call["max_completion_tokens"] for call in recorder.calls}
    assert caps["Proposed Solution"] > caps["Declaration & Authorised Undertaking"]


async def test_sse_contract_is_preserved(generation_proposal, recorder):
    events = await _run_generation(generation_proposal.id)

    names = [name for name, _ in events]
    assert names[0] == "section_start"
    assert names[-1] == "done"
    assert set(names) == {"section_start", "section_chunk", "section_done", "done"}

    starts = [data["name"] for name, data in events if name == "section_start"]
    dones = [data["name"] for name, data in events if name == "section_done"]
    assert starts == [definition["title"] for definition in SECTION_DEFINITIONS]
    assert sorted(dones) == sorted(starts)

    for name, data in events:
        if name == "section_chunk":
            # `content` unchanged; `name` added so concurrent chunks can be
            # attributed to a section.
            assert set(data) == {"content", "name"}
            assert data["name"] in starts
        elif name in ("section_start", "section_done"):
            assert set(data) == {"name"}
        else:
            assert data == {}


async def test_streamed_chunks_reassemble_to_the_stored_content(generation_proposal, recorder, db):
    from sqlalchemy import select

    from database.models import ProposalSection

    events = await _run_generation(generation_proposal.id)

    streamed: dict[str, str] = {}
    for name, data in events:
        if name == "section_chunk":
            streamed[data["name"]] = streamed.get(data["name"], "") + data["content"]

    rows = (
        (await db.execute(select(ProposalSection).where(ProposalSection.proposal_id == generation_proposal.id)))
        .scalars()
        .all()
    )
    for row in rows:
        assert streamed[row.title].strip() == row.content


async def test_proposal_lands_in_review_with_markdown_uploaded(generation_proposal, recorder, db, fake_s3):
    await _run_generation(generation_proposal.id)
    await db.refresh(generation_proposal)

    assert generation_proposal.status == ProposalStatus.REVIEW
    assert generation_proposal.markdown_path.endswith("proposal.md")
    assert generation_proposal.markdown_path in fake_s3.uploaded


async def test_empty_section_fails_the_run_instead_of_persisting_a_hole(generation_proposal, recorder, db):
    """The regression this whole change is about."""

    from sqlalchemy import select

    from database.models import ProposalSection

    recorder.fail_for = {"Proposed Solution"}

    events = await _run_generation(generation_proposal.id)

    assert events[-1][0] == "error"
    assert "reasoning_effort" in events[-1][1]["message"]
    assert "done" not in [name for name, _ in events]

    await db.refresh(generation_proposal)
    assert generation_proposal.status == ProposalStatus.FAILED
    assert "Proposed Solution" in generation_proposal.error_message

    rows = (
        (await db.execute(select(ProposalSection).where(ProposalSection.proposal_id == generation_proposal.id)))
        .scalars()
        .all()
    )
    # The failing section is absent; the ones that completed stay persisted.
    assert all(row.title != "Proposed Solution" for row in rows)
    assert all(row.content.strip() for row in rows)


async def test_truncated_section_fails_the_run(generation_proposal, recorder, db):
    recorder.finish_reason = "length"

    events = await _run_generation(generation_proposal.id)

    assert events[-1][0] == "error"
    await db.refresh(generation_proposal)
    assert generation_proposal.status == ProposalStatus.FAILED


async def test_default_concurrency_is_one_and_serializes_drafting(generation_proposal, recorder):
    """Default config must reproduce the original sequential behaviour exactly."""

    assert config.generation.resolved_concurrency == 1

    recorder.delay = 0.001
    await _run_generation(generation_proposal.id)

    assert recorder.max_concurrent == 1


async def test_concurrency_is_capped_at_the_configured_value(
    generation_proposal, recorder, monkeypatch, serialized_db_sessions
):
    monkeypatch.setenv("GENERATION_CONCURRENCY", "3")
    assert config.generation.resolved_concurrency == 3

    recorder.delay = 0.001
    await _run_generation(generation_proposal.id)

    # Never more than the cap, and it genuinely overlapped.
    assert recorder.max_concurrent <= 3
    assert recorder.max_concurrent > 1


async def test_concurrent_sections_still_persist_correct_order_index(
    generation_proposal, recorder, monkeypatch, db, serialized_db_sessions
):
    """Sections may complete out of order; document order comes from
    order_index, not completion order."""

    from sqlalchemy import select

    from database.models import ProposalSection

    monkeypatch.setenv("GENERATION_CONCURRENCY", "4")
    await _run_generation(generation_proposal.id)

    rows = (
        (await db.execute(select(ProposalSection).where(ProposalSection.proposal_id == generation_proposal.id)))
        .scalars()
        .all()
    )
    by_index = {row.order_index: row.section_key for row in rows}
    assert by_index == {index: definition["key"] for index, definition in enumerate(SECTION_DEFINITIONS)}


async def test_env_var_overrides_config_and_ignores_garbage(monkeypatch):
    monkeypatch.setenv("GENERATION_CONCURRENCY", "6")
    assert config.generation.resolved_concurrency == 6

    monkeypatch.setenv("GENERATION_CONCURRENCY", "nonsense")
    assert config.generation.resolved_concurrency == config.generation.concurrency

    monkeypatch.setenv("GENERATION_CONCURRENCY", "0")
    assert config.generation.resolved_concurrency == config.generation.concurrency
