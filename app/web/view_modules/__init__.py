"""version: 1.0.0
description: Public exports for MP Control web view modules.
updated: 2026-06-09
"""

# ruff: noqa: F401, F403, I001

from app.web.view_modules import admin as admin
from app.web.view_modules import catalog as catalog
from app.web.view_modules import common as common
from app.web.view_modules import components as components
from app.web.view_modules import dashboard as dashboard
from app.web.view_modules import forms as forms
from app.web.view_modules import formatting as formatting
from app.web.view_modules import orders as orders
from app.web.view_modules import planning as planning
from app.web.view_modules import pricing as pricing
from app.web.view_modules import profit as profit
from app.web.view_modules import reports as reports
from app.web.view_modules import settings as settings

from app.web.view_modules.admin import *  # noqa: F401,F403
from app.web.view_modules.catalog import *  # noqa: F401,F403
from app.web.view_modules.common import *  # noqa: F401,F403
from app.web.view_modules.components import *  # noqa: F401,F403
from app.web.view_modules.dashboard import *  # noqa: F401,F403
from app.web.view_modules.forms import *  # noqa: F401,F403
from app.web.view_modules.formatting import *  # noqa: F401,F403
from app.web.view_modules.orders import *  # noqa: F401,F403
from app.web.view_modules.planning import *  # noqa: F401,F403
from app.web.view_modules.pricing import *  # noqa: F401,F403
from app.web.view_modules.profit import *  # noqa: F401,F403
from app.web.view_modules.reports import *  # noqa: F401,F403
from app.web.view_modules.settings import *  # noqa: F401,F403

__all__ = [
    *admin.__all__,
    *catalog.__all__,
    *common.__all__,
    *components.__all__,
    *dashboard.__all__,
    *forms.__all__,
    *formatting.__all__,
    *orders.__all__,
    *planning.__all__,
    *pricing.__all__,
    *profit.__all__,
    *reports.__all__,
    *settings.__all__,
]
