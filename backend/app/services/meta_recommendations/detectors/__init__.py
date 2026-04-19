"""Meta detector implementations.

Each module registers one or more detectors via @register. Importing this
package triggers all @register decorators exactly once.
"""

from app.services.meta_recommendations.detectors import (  # noqa: F401
    performance,
    creative_fatigue,
    seasonal,
    audience_hygiene,
)
