"""Inline system-browser sign-in for the Linux launcher."""


def login_banner(parent=None, *, force_login=False):
    from oauth_browser import browser_login_banner
    return browser_login_banner(parent, force_login=force_login)


# The old factory name now also creates an inline widget; no modal auth UI remains.
login_dialog = login_banner
