"""HTML bodies for outbound transactional email.

Why the markup looks dated: email clients are not browsers. Outlook renders
through Word, Gmail strips <style> blocks in some views, and none of them can
be relied on for flexbox, grid, CSS variables, external stylesheets or web
fonts. So everything here is a nested <table> with inline styles — the only
layout that survives every client. Keep it that way when adding a template.

Colours mirror the default export template (html/template_1.html): #0d2b5e for
the header/heading and #1a5fb4 for the button, so mail and documents look like
they come from the same product. Change them in both places.
"""

from html import escape

from config import config

BRAND_HEADING = "#0d2b5e"   # mirrors html/template_1.html --heading
BRAND_BUTTON = "#1a5fb4"    # mirrors html/template_1.html --subheading
BRAND_NAME = "Proposal AI"

_TEXT = "#1a1a1a"
_MUTED = "#5b6675"
_RULE = "#e3e8ef"
_PAGE_BG = "#e9edf2"
_PANEL_BG = "#f5f8fc"


def _layout(*, preheader: str, heading: str, content: str) -> str:
    """Shared shell: page background, brand header, white card, footer.

    `preheader` is the grey snippet a client shows next to the subject in the
    inbox list. Without one, clients pull the first text they find in the body,
    which would be the heading repeated back — so it's set explicitly and then
    hidden from the rendered mail.
    """

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{escape(heading)}</title>
</head>
<body style="margin:0; padding:0; background-color:{_PAGE_BG}; \
font-family:Arial,'Helvetica Neue',Helvetica,sans-serif; color:{_TEXT};">

  <div style="display:none; font-size:1px; line-height:1px; max-height:0; max-width:0; \
opacity:0; overflow:hidden;">{escape(preheader)}</div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:{_PAGE_BG}; padding:32px 12px;">
    <tr>
      <td align="center">

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px; background-color:#ffffff; border-radius:10px; overflow:hidden;
                      box-shadow:0 4px 18px rgba(13,43,94,0.10);">

          <!-- header -->
          <tr>
            <td align="center" style="background-color:{BRAND_HEADING}; padding:26px 32px;">
              <div style="font-size:20px; font-weight:bold; color:#ffffff; letter-spacing:0.5px;">
                {escape(BRAND_NAME)}
              </div>
            </td>
          </tr>

          <!-- body -->
          <tr>
            <td style="padding:36px 32px 12px 32px;">
              <h1 style="margin:0 0 18px 0; font-size:22px; line-height:1.3;
                         color:{BRAND_HEADING}; font-weight:bold;">
                {escape(heading)}
              </h1>
              {content}
            </td>
          </tr>

          <!-- footer -->
          <tr>
            <td style="padding:24px 32px 30px 32px; border-top:1px solid {_RULE};">
              <p style="margin:0; font-size:12px; line-height:1.6; color:{_MUTED};">
                This is an automated message from {escape(BRAND_NAME)}. If you weren't
                expecting it, you can safely ignore this email.
              </p>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>
"""


def _button(*, url: str, label: str) -> str:
    """A padded, rounded anchor rather than a <button> — form controls don't
    render in mail. The URL is escaped for the attribute *and* shown as plain
    text underneath, because a fair number of clients block linked text until
    the recipient marks the sender as trusted."""

    safe_url = escape(url, quote=True)
    return f"""\
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="margin:26px 0 8px 0;">
                <tr>
                  <td align="center" bgcolor="{BRAND_BUTTON}" style="border-radius:6px;">
                    <a href="{safe_url}"
                       style="display:inline-block; padding:13px 30px; font-size:15px;
                              font-weight:bold; color:#ffffff; text-decoration:none;
                              border-radius:6px;">
                      {escape(label)}
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 6px 0; font-size:12px; line-height:1.6; color:{_MUTED};">
                Or paste this link into your browser:<br />
                <a href="{safe_url}" style="color:{BRAND_BUTTON};">{escape(url)}</a>
              </p>
"""


def _credentials_panel(rows: list[tuple[str, str]]) -> str:
    """Label/value pairs on a tinted panel. Values are monospaced so an
    invitee retyping a password can tell the characters apart, and carry
    `user-select:all` so a tap selects the whole value on mobile."""

    cells = "".join(
        f"""
                  <tr>
                    <td style="padding:6px 0; font-size:12px; color:{_MUTED};
                               text-transform:uppercase; letter-spacing:0.6px;">
                      {escape(label)}
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 0 14px 0; font-size:16px; font-weight:bold;
                               color:{BRAND_HEADING}; font-family:'Courier New',Courier,monospace;
                               word-break:break-all; user-select:all;">
                      {escape(value)}
                    </td>
                  </tr>"""
        for label, value in rows
    )

    return f"""\
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                     style="background-color:{_PANEL_BG}; border:1px solid {_RULE};
                            border-left:4px solid {BRAND_BUTTON}; border-radius:6px;
                            margin:8px 0 4px 0;">
                <tr>
                  <td style="padding:18px 22px 4px 22px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{cells}
                    </table>
                  </td>
                </tr>
              </table>
"""


def _paragraph(text: str, *, muted: bool = False) -> str:
    colour = _MUTED if muted else _TEXT
    size = "13px" if muted else "15px"
    return (
        f'              <p style="margin:0 0 16px 0; font-size:{size}; line-height:1.65; '
        f'color:{colour};">{text}</p>\n'
    )


def team_invite_email(*, to_email: str, temporary_password: str, login_url: str) -> tuple[str, str]:
    """The team-invite body, as ``(plain_text, html)``.

    Both parts are built here so they can't drift apart — every client gets one
    of the two, and the text part is what plain-text-only readers and spam
    filters see.
    """

    text = (
        "Hello,\n\n"
        f"You have been invited to join {BRAND_NAME}.\n\n"
        "Your login credentials are:\n\n"
        "Email:\n"
        f"{to_email}\n\n"
        "Temporary Password:\n"
        f"{temporary_password}\n\n"
        f"Log in here: {login_url}\n\n"
        "You'll be asked to set your own password the first time you sign in.\n\n"
        "Regards,\n"
        f"{BRAND_NAME} Team"
    )

    content = (
        _paragraph(f"You've been invited to join <strong>{escape(BRAND_NAME)}</strong>. "
                   "Use the credentials below to sign in for the first time.")
        + _credentials_panel([("Email", to_email), ("Temporary password", temporary_password)])
        + _button(url=login_url, label="Log in to " + BRAND_NAME)
        + _paragraph("For your security, you'll be asked to set your own password the first "
                     "time you sign in. Until then, keep this temporary password to yourself.",
                     muted=True)
    )

    html = _layout(
        preheader=f"Your {BRAND_NAME} login details are inside.",
        heading="You're invited to " + BRAND_NAME,
        content=content,
    )
    return text, html


def resolve_login_url() -> str:
    """Single place the invite flow reads the app URL from, so call sites
    don't each reach into config for it."""

    return config.base_url
