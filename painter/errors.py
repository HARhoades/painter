"""Errors the services raise, for every front end to present its own way.

The HTTP ones subclass requests.HTTPError, so existing `except
requests.HTTPError` handlers still catch them, and `.response` is set.
This is the minimal slice of the phase 3 error hierarchy needed for review
finding 9: telling "not found" apart from a bad token, no permission, or
Canvas being down.
"""
from __future__ import annotations

import requests


class PainterError(Exception):
    """Base for every error Painter raises on purpose.

    .notes holds anything the service had to say before failing (same shape
    as events.Note), so a front end can show it ahead of the error."""

    notes: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notes = []


class InvalidInput(PainterError, ValueError):
    """Something the user supplied cannot be used (a spec that matches
    nothing, an unreadable file, options that do not go together)."""


class MissingDependency(PainterError):
    """An optional package (openpyxl, playwright) is needed and not installed."""


class BrowserUnavailable(PainterError):
    """The browser could not be started, reached, or signed in to Canvas."""


class Cancelled(PainterError):
    """The front end asked the service to stop (Reporter.cancelled())."""


class CanvasHTTPError(requests.HTTPError, PainterError):
    """Canvas (or a file store) answered with an error status."""

    hint = ""


class AuthFailed(CanvasHTTPError):
    hint = ("Canvas rejected the API token (401). Check that CANVAS_API_TOKEN "
            "holds a current token for this Canvas address.")


class Forbidden(CanvasHTTPError):
    hint = ("Canvas refused access (403). The token's account may not have "
            "permission for this course or action.")


class NotFound(CanvasHTTPError):
    hint = "Canvas has no such item (404). Check the IDs."


class CanvasUnavailable(CanvasHTTPError):
    hint = "Canvas is not answering normally (server error). Try again later."


def error_for_status(resp: requests.Response) -> CanvasHTTPError | None:
    """The typed error for a failed response, or None if it succeeded."""
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        code = resp.status_code
        cls = (AuthFailed if code == 401 else Forbidden if code == 403
               else NotFound if code == 404
               else CanvasUnavailable if code >= 500 else CanvasHTTPError)
        return cls(str(exc), response=resp, request=getattr(resp, "request", None))
    return None
