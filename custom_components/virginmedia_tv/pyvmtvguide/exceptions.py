"""Custom Exceptions."""


class VirginMediaTVGuideError(Exception):
    """General error."""


class VirginMediaTVGuideForbidden(VirginMediaTVGuideError):
    """Forbidden error for the API."""


class VirginMediaTVGuideUnauthorized(VirginMediaTVGuideError):
    """Unauthorised for the API."""
