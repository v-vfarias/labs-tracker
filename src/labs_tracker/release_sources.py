"""Compatibility imports; new code should import the owning package."""

from .integrations.release_sources import (
    PRODUCT_SOURCES as PRODUCT_SOURCES,
    TRUSTED_HOSTS as TRUSTED_HOSTS,
    source_for_product as source_for_product,
    check_source_url as check_source_url,
    save_source_urls as save_source_urls,
    source_validation as source_validation,
    validate_source as validate_source,
    validate_all_sources as validate_all_sources,
)
