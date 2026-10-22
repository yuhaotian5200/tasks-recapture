"""Errors raised by the recapture flow. None of them grant execution rights."""


class RecaptureError(Exception):
    """Base error. The message is safe to show; it never includes API keys."""


class ConfigError(RecaptureError):
    """The configuration is missing or refuses to start."""


class MissingAPIKey(RecaptureError):
    """A live call was requested and TASKS_RECAPTURE_API_KEY is unset."""


class SendNotConfirmed(RecaptureError):
    """A live call needs an explicit --send flag before any network use."""


class ValidationError(RecaptureError):
    """Model output or a transcript failed a program check."""


class ConflictError(RecaptureError):
    """A card changed between preview and write, so the write was refused."""


class StoreError(RecaptureError):
    """A task file could not be read or written safely."""
