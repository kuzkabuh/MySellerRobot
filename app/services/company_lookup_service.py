"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.company_lookup_service.
updated: 2026-06-09
"""

from app.services.account.company_lookup_service import (  # noqa: F401
    CompanyLookupError,
    CompanyLookupResult,
    CompanyLookupService,
    CompanyProfileDTO,
    DadataNotConfiguredError,
    map_dadata_party_to_company_profile,
    normalize_inn,
    validate_inn,
)

__all__ = ['CompanyLookupError', 'CompanyLookupResult', 'CompanyLookupService', 'CompanyProfileDTO', 'DadataNotConfiguredError', 'map_dadata_party_to_company_profile', 'normalize_inn', 'validate_inn']
