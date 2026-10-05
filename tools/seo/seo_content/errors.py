"""Shared failure types, usable without model adapters or generation modules."""


class ProviderError(RuntimeError):
    def __init__(self, reason, *, retryable=True, retry_after=None):
        super().__init__(reason)
        self.retryable = retryable
        self.retry_after = retry_after
        self.detail = None


class StageError(ProviderError):
    """Model output failed its schema; discard this candidate, not the entire run."""


class BudgetExhausted(ProviderError):
    pass


class ContentApiError(ProviderError):
    """A content API failure. 4xx client errors are not retried; network and 5xx/429 are."""

    def __init__(self, reason, *, status=None, retryable=True):
        super().__init__(reason, retryable=retryable)
        self.status = status


class ReviewError(Exception):
    pass
