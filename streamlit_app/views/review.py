"""Step 3 — Review & Refine."""

import streamlit as st

from services.api_client import APIError
from services.auth import access_token, get_api_client
from utils.activity import log_activity
from utils.formatting import confidence_color, confidence_label, proposal_status_badge, section_status_badge

OPTIONAL_REQUIREMENT_FIELDS = [
    ("project_type", "Project Type"),
    ("budget_range", "Budget Range"),
    ("timeline", "Timeline"),
    ("evaluation_criteria", "Evaluation Criteria"),
    ("constraints", "Constraints"),
]


def _update_section_in_state(updated_section: dict) -> None:
    proposal = st.session_state.proposal
    for index, section in enumerate(proposal["sections"]):
        if section["id"] == updated_section["id"]:
            proposal["sections"][index] = updated_section
            break
    st.session_state.proposal = proposal


def _section_stats(sections: list) -> dict:
    total = len(sections)
    approved = sum(1 for s in sections if s["status"] == "approved")
    needs_revision = sum(1 for s in sections if s["status"] == "needs_revision")
    pending = sum(1 for s in sections if s["status"] == "pending")
    scored = [s["confidence_score"] for s in sections if s.get("confidence_score") is not None]
    avg_confidence = sum(scored) / len(scored) if scored else None
    return {
        "total": total,
        "approved": approved,
        "needs_revision": needs_revision,
        "pending": pending,
        "avg_confidence": avg_confidence,
    }


def _render_summary_and_status(proposal: dict, requirement_document: dict, stats: dict) -> None:
    st.markdown('<div class="app-card-title">🧾 Proposal Summary</div>', unsafe_allow_html=True)
    st.markdown(
        f"""<div class="app-card">
        <b>{proposal.get('title')}</b><br/>
        <span class="app-card-subtle">Client: {proposal.get('client_name') or requirement_document.get('client_name', '—')}</span>
        </div>""",
        unsafe_allow_html=True,
    )
    summary = (requirement_document or {}).get("summary")
    if summary:
        with st.expander("Requirement Summary (extracted from the RFP)", expanded=False):
            st.markdown(summary)

    st.markdown('<div class="app-card-title">🔄 Workflow Status</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="app-card">{proposal_status_badge(proposal.get("status"))} &nbsp; '
        f'<span class="app-card-subtle">{stats["approved"]} of {stats["total"]} sections approved</span></div>',
        unsafe_allow_html=True,
    )


def _render_statistics(stats: dict) -> None:
    st.markdown('<div class="app-card-title">📊 Statistics</div>', unsafe_allow_html=True)
    tiles = [
        ("Total Sections", stats["total"]),
        ("Approved", stats["approved"]),
        ("Needs Revision", stats["needs_revision"]),
        ("Pending", stats["pending"]),
    ]
    cols = st.columns(4)
    for col, (label, value) in zip(cols, tiles):
        with col:
            st.markdown(
                f'<div class="stat-tile"><div class="stat-value">{value}</div>'
                f'<div class="stat-label">{label}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="app-card-title">🎯 Confidence</div>', unsafe_allow_html=True)
    color = confidence_color(stats["avg_confidence"])
    st.markdown(
        f'<div class="stat-tile" style="max-width:220px;">'
        f'<div class="stat-value" style="color:{color};">{confidence_label(stats["avg_confidence"])}</div>'
        f'<div class="stat-label">Average across sections</div></div>',
        unsafe_allow_html=True,
    )


def _render_requirements_coverage(requirement_document: dict) -> None:
    parsed = (requirement_document or {}).get("parsed_requirements") or {}

    st.markdown('<div class="app-card-title">✅ Requirements Covered</div>', unsafe_allow_html=True)
    technical = parsed.get("technical_requirements") or []
    deliverables = parsed.get("deliverables") or []
    if not technical and not deliverables:
        st.markdown(
            '<div class="app-card-subtle">No structured requirements were extracted from the source document.</div>',
            unsafe_allow_html=True,
        )
    else:
        col1, col2 = st.columns(2)
        with col1:
            if technical:
                st.markdown("**Technical Requirements**")
                for item in technical:
                    st.markdown(f"- {item}")
        with col2:
            if deliverables:
                st.markdown("**Deliverables**")
                for item in deliverables:
                    st.markdown(f"- {item}")

    st.markdown('<div class="app-card-title">❓ Missing Information</div>', unsafe_allow_html=True)
    missing = [label for key, label in OPTIONAL_REQUIREMENT_FIELDS if not parsed.get(key)]
    if missing:
        st.warning("Not specified in the source document: " + ", ".join(missing))
    else:
        st.success("All optional requirement fields were specified in the source document.")


def _render_review_flags(sections: list) -> None:
    st.markdown('<div class="app-card-title">🚩 Review Flags</div>', unsafe_allow_html=True)
    flagged = [s for s in sections if s.get("review_flag")]
    if not flagged:
        st.markdown('<div class="app-card-subtle">No sections currently flagged for review.</div>', unsafe_allow_html=True)
        return
    for section in flagged:
        title = section["section_key"].replace("_", " ").title()
        st.markdown(f"- **{title}** — confidence {confidence_label(section.get('confidence_score'))}")


def _render_section_card(client, section: dict) -> None:
    title = section["section_key"].replace("_", " ").title()
    flag = " 🚩" if section.get("review_flag") else ""

    with st.expander(f"{title}{flag}", expanded=False):
        st.markdown(section_status_badge(section["status"]), unsafe_allow_html=True)
        st.caption(f"Confidence: {confidence_label(section.get('confidence_score'))}")

        view_tab, edit_tab = st.tabs(["View", "Edit"])
        with view_tab:
            st.markdown(section.get("content") or "_No content yet._")
            sources = section.get("sources") or []
            if sources:
                with st.expander("Sources", expanded=False):
                    for src in sources:
                        st.caption(f"- {src.get('breadcrumb', src)}")

        with edit_tab:
            new_content = st.text_area(
                "Content", value=section.get("content") or "", key=f"edit_content_{section['id']}", height=220
            )
            if st.button("💾 Save changes", key=f"save_{section['id']}"):
                try:
                    updated = client.edit_section(
                        access_token=access_token(), section_id=section["id"], content=new_content
                    )
                except APIError as exc:
                    st.error(exc.detail)
                else:
                    _update_section_in_state(updated)
                    log_activity(f"Edited section '{title}'", icon="✏️")
                    st.rerun()

        button_cols = st.columns(2)
        with button_cols[0]:
            if st.button("🔄 Regenerate", key=f"regen_{section['id']}", use_container_width=True):
                with st.spinner("Regenerating section..."):
                    try:
                        updated = client.regenerate_section(access_token=access_token(), section_id=section["id"])
                    except APIError as exc:
                        st.error(exc.detail)
                    else:
                        _update_section_in_state(updated)
                        log_activity(f"Regenerated section '{title}'", icon="🔄")
                        st.rerun()
        with button_cols[1]:
            if st.button(
                "✅ Approve",
                key=f"approve_{section['id']}",
                use_container_width=True,
                disabled=section["status"] == "approved",
            ):
                try:
                    updated = client.approve_section(access_token=access_token(), section_id=section["id"])
                except APIError as exc:
                    st.error(exc.detail)
                else:
                    _update_section_in_state(updated)
                    log_activity(f"Approved section '{title}'", icon="✅")
                    st.rerun()


def render_review_page() -> None:
    proposal = st.session_state.get("proposal")
    if not proposal:
        st.warning("No proposal loaded — start again from Upload Requirements.")
        if st.button("← Back to Upload"):
            st.session_state.workflow_stage = "upload"
            st.rerun()
        return

    requirement_document = st.session_state.get("requirement_document") or {}
    client = get_api_client()

    st.title("📝 Review & Refine")
    st.caption("Step 3 of 4 — review each generated section, edit or regenerate as needed, then approve.")

    sections = proposal.get("sections") or []
    stats = _section_stats(sections)

    _render_summary_and_status(proposal, requirement_document, stats)
    _render_statistics(stats)
    _render_requirements_coverage(requirement_document)
    _render_review_flags(sections)

    st.divider()
    st.subheader("Generated Sections")
    for section in sorted(sections, key=lambda s: s["order_index"]):
        _render_section_card(client, section)

    st.divider()
    all_approved = stats["total"] > 0 and stats["approved"] == stats["total"]
    if not all_approved:
        st.caption("Tip: approve all sections before exporting for a clean final document.")
    if st.button("Continue to Export →", type="primary"):
        st.session_state.workflow_stage = "export"
        st.rerun()
