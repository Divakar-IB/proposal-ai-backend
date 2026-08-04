def generate_proposal_name(
    client_name: str,
    project_title: str,
    organization_name: str | None = None,
    template: str | None = None,
) -> str:
    """Builds a human-readable proposal name, e.g.
    "ABC Technologies - ERP Modernization Proposal", or, when an
    organization name is configured, "InnoBoon - ABC Technologies - ERP
    Modernization Proposal".

    `template` is OrganizationSettings.proposal_naming_template — a
    `.format()`-style string with {organization_name}/{client_name}/
    {project_title} placeholders, e.g.
    "{organization_name} - {client_name} - {project_title} Proposal".
    When unset (or malformed / referencing an unknown placeholder), falls
    back to joining whichever of organization_name/client_name/project_title
    are actually present."""

    if template:
        try:
            name = template.format(
                organization_name=organization_name or "",
                client_name=client_name,
                project_title=project_title,
            ).strip()
            if name:
                return name
        except (KeyError, IndexError):
            pass  # malformed/unknown placeholder — fall through to the default below

    parts = [part for part in (organization_name, client_name, project_title) if part]
    if not parts:
        return "Untitled Proposal"
    return " - ".join(parts) + " Proposal"
