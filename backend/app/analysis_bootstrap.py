"""Application composition for the independent analysis worker."""


def bind_analysis_callbacks() -> None:
    # The route module owns the concrete callbacks and registers them on import.
    # Keep this API dependency in application composition, outside core services.
    from .api import routes_analysis  # noqa: F401
