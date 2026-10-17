"""Application errors carry a translation key; the API layer turns them into JSON responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400

    def __init__(self, code: str, status_code: int | None = None, **params: Any) -> None:
        super().__init__(code)
        self.code = code
        self.params = params
        if status_code is not None:
            self.status_code = status_code


class NotFound(AppError):
    status_code = 404

    def __init__(self, code: str = "errors.not_found", **params: Any) -> None:
        super().__init__(code, **params)


class Forbidden(AppError):
    status_code = 403

    def __init__(self, code: str = "errors.forbidden", **params: Any) -> None:
        super().__init__(code, **params)


class Unauthorized(AppError):
    status_code = 401

    def __init__(self, code: str = "errors.unauthorized", **params: Any) -> None:
        super().__init__(code, **params)


class Conflict(AppError):
    status_code = 409


class NeedsConfirmation(AppError):
    """An agent tried a destructive or billing-relevant action; a human must confirm it."""

    status_code = 202

    def __init__(self, confirmation_id: str) -> None:
        super().__init__("errors.needs_confirmation", confirmation_id=confirmation_id)
        self.confirmation_id = confirmation_id
