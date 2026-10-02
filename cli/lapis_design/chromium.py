"""Start Chromium for `render check` and `behavior check`, and say in one line what to do when it will not start.

Playwright's text for a missing browser tells the user to run `playwright install`, a command that is not on
PATH after `uv tool install`, and for a browser that is installed but cannot start (an agent sandbox, a
missing permission) it prints the launch flags and logs. Neither tells an agent what to do next, so a
failed launch ends the check with one line of ours; the check is then not run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lapis_design import browser_install_command

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Playwright


class BrowserUnavailable(RuntimeError):
    """Chromium is missing or cannot start; the message is the one line that says what to do."""


def launch(playwright: Playwright, args: list[str]) -> Browser:
    from playwright.sync_api import Error as PlaywrightError
    try:
        return playwright.chromium.launch(args=args)
    except PlaywrightError as exc:
        reason = (str(exc).splitlines() or [""])[0]
        if "Executable doesn't exist" in reason:
            raise BrowserUnavailable(f"the browser is not installed; run {browser_install_command()} "
                                     "and run the check again") from None
        raise BrowserUnavailable(f"the browser is installed but could not start ({reason}); a sandbox or a missing "
                                 "permission is the usual cause, so allow it to start Chromium, or report this "
                                 "check as not run") from None
