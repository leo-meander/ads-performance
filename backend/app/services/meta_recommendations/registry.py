"""Detector registry (Meta).

Detectors register themselves via the `@register` decorator. The orchestrator
looks them up by cadence tag (daily | weekly | monthly | seasonality) or
retrieves all of them for administrative runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.meta_recommendations.base import Detector


_REGISTRY: dict[str, type["Detector"]] = {}


def register(cls: type["Detector"]) -> type["Detector"]:
    """Class decorator: register a Detector subclass by its rec_type."""
    rec_type = getattr(cls, "rec_type", "")
    if not rec_type:
        raise ValueError(f"{cls.__name__} has no rec_type attribute")
    if rec_type in _REGISTRY:
        raise ValueError(
            f"rec_type {rec_type!r} already registered by "
            f"{_REGISTRY[rec_type].__name__}; cannot re-register with {cls.__name__}",
        )
    _REGISTRY[rec_type] = cls
    return cls


def all_detectors() -> list["Detector"]:
    _ensure_loaded()
    return [cls() for cls in _REGISTRY.values()]


def by_cadence(cadence: str) -> list["Detector"]:
    _ensure_loaded()
    out: list["Detector"] = []
    for cls in _REGISTRY.values():
        det = cls()
        if det.cadence == cadence:
            out.append(det)
    return out


def get_detector(rec_type: str) -> "Detector":
    _ensure_loaded()
    cls = _REGISTRY.get(rec_type)
    if cls is None:
        raise KeyError(f"No detector registered for rec_type={rec_type!r}")
    return cls()


def registered_rec_types() -> set[str]:
    _ensure_loaded()
    return set(_REGISTRY.keys())


def _ensure_loaded() -> None:
    """Import the detectors package once so every @register decorator runs."""
    import app.services.meta_recommendations.detectors  # noqa: F401
