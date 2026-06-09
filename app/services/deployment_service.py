"""version: 1.1.0
description: Compatibility facade. Moved to app.services.admin.deployment_service.
updated: 2026-06-09
"""

from app.services.admin.deployment_service import (  # noqa: F401
    DeploymentService,
)

__all__ = ['DeploymentService']
