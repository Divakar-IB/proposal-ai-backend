"""Per-request *token* sizing for proposal drafting.

Distinct from generation/length_budget.py, which allocates *words* across
sections to hit a page count. This module converts one section's word target
into the `max_completion_tokens` its request should reserve, and then clamps
that against Groq's tokens-per-minute ceiling.

Both halves are necessary and they pull in opposite directions:

- Without an explicit cap, `gpt-oss` can spend an unbounded share of its
  allowance on reasoning tokens that are billed but never streamed, and the
  section arrives empty (see config.GenerationConfig.reasoning_effort).
- With a cap derived purely from the word target, the largest sections ask for
  more than the TPM limit allows in a single request, and Groq answers 413
  "Request too large" — which, unlike a 429, no amount of waiting fixes.

So the cap is derived from the word target and then clamped to what a single
request may occupy.
"""

from typing import Optional

from chunking.tokenization import count_tokens
from config import config

# English prose runs a little over one token per word under cl100k_base;
# Markdown headings, bullets and table pipes push it higher. Measured against
# real drafted sections this lands close to 1.3.
TOKENS_PER_WORD = 1.3

# Added on top of the converted word target. Covers the section's "### "
# subsection headings, the low-effort reasoning preamble (~25-40 tokens
# measured), and the model overshooting its upper word bound slightly — all of
# which would otherwise be paid for out of the body and truncate it.
COMPLETION_HEADROOM_TOKENS = 320

# Never reserve less than this, however small the section's word target. A
# 60-word MIN_SECTION_WORDS section still has to fit a reasoning preamble
# before it writes anything.
MIN_COMPLETION_TOKENS = 256


def completion_tokens_for(word_target: int) -> int:
    """`max_completion_tokens` for a section with this word budget."""

    return max(int(word_target * TOKENS_PER_WORD) + COMPLETION_HEADROOM_TOKENS, MIN_COMPLETION_TOKENS)


def estimate_prompt_tokens(messages: list[dict]) -> int:
    """Approximate prompt cost of a chat-completions message list.

    cl100k_base is not gpt-oss's tokenizer, so this is an estimate — which is
    exactly why config.groq.request_budget_ratio leaves a margin rather than
    letting a request plan to occupy the whole limit. The per-message constant
    covers the role/delimiter overhead the API adds around each message.
    """

    return sum(count_tokens(str(message.get("content") or "")) + 4 for message in messages)


def max_request_tokens() -> int:
    """Prompt + reserved completion ceiling for a single request."""

    return max(int(config.groq.tokens_per_minute * config.groq.request_budget_ratio), 1000)


def clamp_completion_tokens(prompt_tokens: int, desired_completion: int) -> tuple[int, bool]:
    """Fit `desired_completion` under the single-request ceiling.

    Returns (granted, was_clamped). `was_clamped` is what the caller logs: a
    clamped section is one whose word target cannot physically be met at this
    TPM tier, and the log line is the only place that becomes visible before
    the draft comes back short.

    A prompt so large that even MIN_COMPLETION_TOKENS doesn't fit still gets
    MIN_COMPLETION_TOKENS, so the returned total can exceed the ceiling. That
    case is not clampable — the prompt is the problem, not the completion — and
    `prompt_exceeds_ceiling` below is how the caller detects it. The request is
    still sent: Groq's tokenizer is the authority and our tiktoken estimate can
    be pessimistic, so rejecting locally would refuse requests that would have
    succeeded.
    """

    available = max_request_tokens() - prompt_tokens
    if desired_completion <= available:
        return desired_completion, False
    return max(available, MIN_COMPLETION_TOKENS), True


def prompt_exceeds_ceiling(prompt_tokens: int) -> bool:
    """True when the prompt alone leaves no usable room for a completion.

    A request in this state is heading for a 413 whatever cap it carries. The
    prompt is dominated by the retrieved-context block
    (generation/nodes.py::TOP_K_SECTION_CHUNKS chunks), so that is the lever.
    """

    return prompt_tokens + MIN_COMPLETION_TOKENS > max_request_tokens()


def describe_budget(prompt_tokens: int, granted_completion: int, limit: Optional[int] = None) -> str:
    """Compact one-line budget summary for the per-section log."""

    ceiling = limit if limit is not None else max_request_tokens()
    return f"prompt~{prompt_tokens}+completion{granted_completion}={prompt_tokens + granted_completion}/{ceiling}"
