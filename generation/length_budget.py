"""Turns the caller's requested `page_count` into a hard per-section word
budget for proposal generation.

Why this exists: the pipeline drafts each section with its own LLM call, so
nothing downstream can enforce a whole-document page limit — the only lever is
telling each section, up front, exactly how many words it may use. Splitting
the budget equally across sections does not work: "Proposed Solution" carries
seven required subsections (five of them use cases) while "Declaration &
Authorised Undertaking" is a single short statement, so an equal split forces
the big sections to overshoot and pads the small ones. Each section therefore
declares a relative `weight` in generation/sections.py and receives that share
of the page budget.
"""

from typing import Any, Iterable

# A page of the exported A4 templates holds roughly this many words of body
# copy at the templates' 10.5pt/1.6-line-height body style.
WORDS_PER_PAGE = 500

# Smallest page count a proposal may be generated at. Every section in
# SECTION_DEFINITIONS is always produced, and several carry seven required
# subsections, so below this the per-section budget cannot cover the mandated
# outlines and sections come back truncated. Enforced at the API boundary by
# schemas.proposal.ProposalGenerateRequest (a 422, rather than silently
# producing a document that misses its page target).
MIN_PROPOSAL_PAGES = 5

# Floor per section. Below this a section cannot state its point at all, so it
# reads as truncated rather than concise. Sections clamped to the floor are
# paid for by shrinking the unclamped ones (see allocate_section_word_targets),
# which keeps the document total on budget.
MIN_SECTION_WORDS = 60

# The drafter is given a range rather than a single number — a single figure
# invites the model to treat it as a target to pad up to. The lower bound is
# what stops sections coming back as one-liners.
LOWER_BOUND_RATIO = 0.75


def _weight_of(definition: dict[str, Any]) -> float:
    weight = float(definition.get("weight", 1.0))
    return weight if weight > 0 else 1.0


def allocate_section_word_targets(page_count: int, definitions: Iterable[dict[str, Any]]) -> dict[str, int]:
    """section key -> word budget, summing to `page_count * WORDS_PER_PAGE`.

    Allocation is proportional to each section's `weight`. Any section whose
    proportional share lands under MIN_SECTION_WORDS is clamped to the floor
    and removed from the pool, then the remaining budget is re-divided among
    the sections still above it — so honouring a floor shrinks the other
    sections instead of inflating the document.

    The only case where the total can exceed the requested budget is when the
    floor alone does (MIN_SECTION_WORDS * section count > budget), i.e. a page
    count too small to fit the section list at all. The caller logs that.
    """

    definitions = list(definitions)
    if not definitions:
        return {}

    budget = max(int(page_count), 1) * WORDS_PER_PAGE
    targets: dict[str, int] = {}
    unclamped = {definition["key"]: _weight_of(definition) for definition in definitions}
    remaining = float(budget)

    # Each pass clamps the sections that fall below the floor at the current
    # share price; removing them raises the share for everyone left, which can
    # pull further sections under the floor — hence the loop.
    while unclamped:
        weight_sum = sum(unclamped.values())
        newly_clamped = [
            key for key, weight in unclamped.items() if remaining * (weight / weight_sum) < MIN_SECTION_WORDS
        ]
        if not newly_clamped:
            break
        for key in newly_clamped:
            targets[key] = MIN_SECTION_WORDS
            remaining -= MIN_SECTION_WORDS
            del unclamped[key]

    if unclamped:
        weight_sum = sum(unclamped.values())
        # Largest-remainder allocation: take the whole-word part of each share,
        # then hand the leftover words to the largest fractional parts. Rounding
        # each share independently would drift the total off budget by a few
        # words per section.
        exact = {key: remaining * (weight / weight_sum) for key, weight in unclamped.items()}
        floors = {key: int(share) for key, share in exact.items()}
        leftover = int(round(remaining)) - sum(floors.values())
        by_remainder = sorted(exact, key=lambda key: exact[key] - floors[key], reverse=True)
        for key in by_remainder[: max(leftover, 0)]:
            floors[key] += 1
        for key, value in floors.items():
            targets[key] = max(value, MIN_SECTION_WORDS)

    # Preserve SECTION_DEFINITIONS order in the returned mapping.
    return {definition["key"]: targets[definition["key"]] for definition in definitions}


def build_length_instruction(word_target: int, page_count: int) -> str:
    """The strict length clause handed to the drafter for one section.

    Deliberately phrased as a hard constraint with an explicit upper bound and
    an instruction on *how* to compress (tighten every subsection rather than
    drop one), because the failure mode we care about is a section that covers
    its required outline but runs three times over budget and blows the
    document's page limit.
    """

    lower = max(int(word_target * LOWER_BOUND_RATIO), MIN_SECTION_WORDS // 2)
    return (
        f"LENGTH REQUIREMENT — STRICT: write between {lower} and {word_target} words for this "
        f"section body.\n"
        f"- The finished proposal must fit {page_count} page(s). Every section draws on that "
        f"same budget, so going over your allocation breaks the whole document.\n"
        f"- Do NOT exceed {word_target} words under any circumstance.\n"
        f"- Cover every required subsection. If the budget is tight, make each subsection "
        f"shorter and denser — never drop one, and never add one that was not asked for.\n"
        f"- Use compact bullet points or a small table instead of long prose when that says "
        f"the same thing in fewer words.\n"
        f"- Do not pad, repeat the requirements back, or add a closing summary just to reach "
        f"the lower bound."
    )
