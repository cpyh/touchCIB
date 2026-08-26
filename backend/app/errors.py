class ValidationError(ValueError):
    """Request data is invalid."""


class NotFoundError(LookupError):
    """Requested business object does not exist."""


class ServiceError(RuntimeError):
    """Database or upstream service failed."""


class UpstreamError(ServiceError):
    """External AI service failed."""
