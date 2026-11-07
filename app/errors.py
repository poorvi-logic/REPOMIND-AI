from __future__ import annotations


class RepoMindError(Exception):
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class InputError(RepoMindError):
    status_code = 400


class NotFoundError(RepoMindError):
    status_code = 404


class PayloadTooLargeError(RepoMindError):
    status_code = 413


class ExternalServiceError(RepoMindError):
    status_code = 502
