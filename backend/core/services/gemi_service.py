import os
import time
from typing import List

from core.models.companies import (
    Company,
    CompanyActivity,
    CompanyCapital,
    CompanyPerson,
    CompanyStock,
)
from core.models.entities import AFMEntity
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from gemi.base_client import BaseAPIClient
from gemi.exceptions import GemiAPIError
from gemi.pagination import PaginatedResponse
from gemi.schemas.company import CompanyResponse
from gemi.services import CompaniesService
from loguru import logger


class GemiService:
    """Django service wrapper for GEMI OpenData API with rate limiting."""

    _companies_service = None
    _rate_limit_key = "gemi_api_calls"

    # GEMI API rate limit (requests per minute)
    # This is the single source of truth for all services that interact with GEMI
    MAX_REQUESTS_PER_MINUTE = getattr(settings, "GEMI_MAX_REQUESTS_PER_MINUTE", 6)

    @classmethod
    def get_companies_service(cls) -> CompaniesService:
        """Get or create the GEMI companies service instance."""
        if cls._companies_service is None:
            api_key = getattr(settings, "GEMI_API_KEY", None) or os.getenv(
                "GEMI_API_KEY"
            )
            if not api_key:
                raise ValueError("GEMI_API_KEY not configured in settings")

            base_client = BaseAPIClient(
                api_key=api_key,
                base_url=getattr(
                    settings,
                    "GEMI_BASE_URL",
                    "https://opendata-api.businessportal.gr/api/opendata/v1",
                ),
                timeout=getattr(settings, "GEMI_TIMEOUT", 30),
                max_retries=getattr(settings, "GEMI_MAX_RETRIES", 3),
            )

            cls._companies_service = CompaniesService(base_client)

        return cls._companies_service

    @classmethod
    def _check_rate_limit(cls, max_requests_per_minute: int = 6) -> float:
        """
        Check rate limit and return delay needed (if any).

        Args:
            max_requests_per_minute: Maximum requests allowed per minute

        Returns:
            float: Seconds to wait before making request (0 if no wait needed)
        """
        current_time = time.time()
        minute_ago = current_time - 60

        # Get recent API calls from cache
        recent_calls = cache.get(cls._rate_limit_key, [])

        # Filter calls within the last minute
        recent_calls = [
            call_time for call_time in recent_calls if call_time > minute_ago
        ]

        if len(recent_calls) >= max_requests_per_minute:
            # Calculate how long to wait
            oldest_call = min(recent_calls)
            wait_until = oldest_call + 60  # 60 seconds from oldest call
            delay = max(0, wait_until - current_time)

            if delay > 0:
                logger.info(f"Rate limit reached. Waiting {delay:.2f} seconds...")
                return delay

        return 0

    @classmethod
    def _record_api_call(cls):
        """Record an API call for rate limiting."""
        current_time = time.time()
        minute_ago = current_time - 60

        # Get recent calls and filter
        recent_calls = cache.get(cls._rate_limit_key, [])
        recent_calls = [
            call_time for call_time in recent_calls if call_time > minute_ago
        ]

        # Add current call
        recent_calls.append(current_time)

        # Store back in cache (expire after 2 minutes to be safe)
        cache.set(cls._rate_limit_key, recent_calls, 120)

    @classmethod
    def _wait_for_rate_limit(cls, max_requests_per_minute: int = 6):
        """Wait if necessary to respect rate limits."""
        delay = cls._check_rate_limit(max_requests_per_minute)
        if delay > 0:
            time.sleep(delay)
        cls._record_api_call()

    @classmethod
    def fetch_companies_by_afm(
        cls,
        afm: str,
        update_entity: bool = True,
        max_requests_per_minute: int = 6,
        force_refresh: bool = False,
        retry_failed_after_days: int = 60,
    ) -> List[Company]:
        """
        Search for companies by AFM and save all results to database.

        Args:
            afm: The AFM to search for
            update_entity: Whether to update the AFMEntity record
            max_requests_per_minute: Rate limit for API calls
            force_refresh: If True, ignore cached failures and retry
            retry_failed_after_days: Days to wait before retrying a failed lookup (default: 7)

        Returns:
            List of Company objects found and saved
        """
        logger.info(f"Fetching companies for AFM: {afm}")

        if not force_refresh:
            # First check if we already have companies for this AFM
            existing_companies = Company.objects.filter(afm=afm)
            if existing_companies.exists():
                logger.info(
                    f"Found {existing_companies.count()} existing companies for AFM {afm}, skipping API call"
                )
                if update_entity:
                    cls._update_afm_entity_after_search(afm, list(existing_companies))
                return list(existing_companies)

            # Check if we've recently tried and failed to find this AFM
            try:
                afm_entity = AFMEntity.objects.get(afm=afm)
                if (
                    afm_entity.gemi_lookup_attempted
                    and not afm_entity.gemi_lookup_success
                ):
                    # Calculate time since last failed attempt
                    time_since_attempt = (
                        timezone.now() - afm_entity.gemi_lookup_attempted
                    )
                    days_since_attempt = time_since_attempt.total_seconds() / (
                        60 * 60 * 24
                    )

                    if days_since_attempt < retry_failed_after_days:
                        logger.info(
                            f"AFM {afm} was unsuccessfully looked up {days_since_attempt:.1f} days ago. "
                            f"Skipping API call (retry after {retry_failed_after_days} days)"
                        )
                        return []
                    else:
                        logger.info(
                            f"AFM {afm} failed lookup was {days_since_attempt:.1f} days ago. "
                            f"Retrying (threshold: {retry_failed_after_days} days)"
                        )
            except AFMEntity.DoesNotExist:
                # No entity yet, proceed with lookup
                pass

        try:
            # Wait for rate limit before search
            cls._wait_for_rate_limit(max_requests_per_minute)

            service = cls.get_companies_service()
            search_response = service.search_companies(vat_number=afm)

            # Handle both paginated and list responses
            if isinstance(search_response, PaginatedResponse):
                companies_summaries = search_response.items
                logger.info(
                    f"Found {len(companies_summaries)} companies for AFM {afm} (paginated)"
                )
            else:
                companies_summaries = search_response
                logger.info(f"Found {len(companies_summaries)} companies for AFM {afm}")

            saved_companies = []

            with transaction.atomic():
                for idx, company_summary in enumerate(companies_summaries):
                    try:
                        # Wait for rate limit before each company detail fetch
                        cls._wait_for_rate_limit(max_requests_per_minute)

                        # Get full company details
                        company_details = service.get_company(
                            company_summary.gemh_number
                        )

                        # Save to database
                        company = cls._save_company_to_db(company_details)
                        saved_companies.append(company)

                        logger.info(
                            f"Saved company {company.ar_gemi} ({company.co_name_el})"
                        )

                    except Exception as e:
                        logger.error(
                            f"Error processing company {company_summary.gemh_number}: {e}"
                        )
                        continue

                # Update AFMEntity if requested
                if update_entity:
                    cls._update_afm_entity_after_search(afm, saved_companies)

            logger.info(
                f"Successfully processed {len(saved_companies)} companies for AFM {afm}"
            )
            return saved_companies

        except GemiAPIError as e:
            logger.debug(f"GEMI API error searching for AFM {afm}: {e}")

            # Still update the entity to mark that we attempted the lookup
            if update_entity:
                cls._update_afm_entity_after_failed_search(afm)

            raise

    @classmethod
    def get_company_info(
        cls, ar_gemi: str, save_to_db: bool = True, max_requests_per_minute: int = 6
    ) -> CompanyResponse:
        """Get company information by AR GEMI and optionally save to database."""
        try:
            # Wait for rate limit
            cls._wait_for_rate_limit(max_requests_per_minute)

            service = cls.get_companies_service()
            company_data = service.get_company(ar_gemi)

            if save_to_db:
                cls._save_company_to_db(company_data)

            return company_data

        except GemiAPIError as e:
            logger.error(f"GEMI API error for AR {ar_gemi}: {e}")
            raise

    @classmethod
    def get_rate_limit_status(cls) -> dict:
        """Get current rate limit status for monitoring."""
        current_time = time.time()
        minute_ago = current_time - 60

        recent_calls = cache.get(cls._rate_limit_key, [])
        recent_calls = [
            call_time for call_time in recent_calls if call_time > minute_ago
        ]

        return {
            "calls_in_last_minute": len(recent_calls),
            "max_calls_per_minute": 6,  # Default, could be made configurable
            "remaining_calls": max(0, 6 - len(recent_calls)),
            "next_reset_in_seconds": (
                60 - (current_time - min(recent_calls)) if recent_calls else 0
            ),
        }

    @classmethod
    def _update_afm_entity_after_search(cls, afm: str, companies: List[Company]):
        """Update AFMEntity after successful company search."""
        try:
            afm_entity, created = AFMEntity.objects.get_or_create(
                afm=afm, defaults={"entity_type": "company" if companies else "unknown"}
            )

            # Update lookup status
            afm_entity.gemi_lookup_attempted = timezone.now()
            afm_entity.gemi_lookup_success = True
            afm_entity.gemi_companies_count = len(companies)

            # Update name and entity type if companies found
            if companies:
                afm_entity.entity_type = "company"
                if not afm_entity.name and companies[0].co_name_el:
                    afm_entity.name = companies[0].co_name_el

            afm_entity.save()
            logger.info(
                f"Updated AFMEntity for {afm}: {len(companies)} companies found"
            )

        except Exception as e:
            logger.error(f"Error updating AFMEntity for {afm}: {e}")

    @classmethod
    def _update_afm_entity_after_failed_search(cls, afm: str):
        """Update AFMEntity after failed company search."""
        try:
            afm_entity, created = AFMEntity.objects.get_or_create(
                afm=afm, defaults={"entity_type": "unknown"}
            )

            afm_entity.gemi_lookup_attempted = timezone.now()
            afm_entity.gemi_lookup_success = False
            afm_entity.gemi_companies_count = 0
            afm_entity.save()

        except Exception as e:
            logger.error(f"Error updating AFMEntity after failed search for {afm}: {e}")

    @classmethod
    def _save_company_to_db(cls, company_data: CompanyResponse) -> Company:
        """Save company data to Django models."""
        try:
            # Create or update the main company record
            company, created = Company.objects.update_or_create(
                ar_gemi=company_data.arGemi,
                defaults={
                    "afm": company_data.afm,
                    "co_name_el": company_data.coNameEl,
                    "co_names_en": company_data.coNamesEn or [],
                    "co_titles_el": company_data.coTitlesEl or [],
                    "co_titles_en": company_data.coTitlesEn or [],
                    "municipality_id": (
                        company_data.municipality.id
                        if company_data.municipality
                        else None
                    ),
                    "municipality_name": (
                        company_data.municipality.descr
                        if company_data.municipality
                        else None
                    ),
                    "prefecture_id": (
                        company_data.prefecture.id if company_data.prefecture else None
                    ),
                    "prefecture_name": (
                        company_data.prefecture.descr
                        if company_data.prefecture
                        else None
                    ),
                    "city": company_data.city,
                    "street": company_data.street,
                    "street_number": company_data.streetNumber,
                    "zip_code": company_data.zipCode,
                    "po_box": company_data.poBox,
                    "url": company_data.url,
                    "email": company_data.email,
                    "is_branch": company_data.isBranch,
                    "objective": company_data.objective,
                    "legal_type_id": (
                        company_data.legalType.id if company_data.legalType else None
                    ),
                    "legal_type_name": (
                        company_data.legalType.descr if company_data.legalType else None
                    ),
                    "gemi_office_id": (
                        company_data.gemiOffice.id if company_data.gemiOffice else None
                    ),
                    "gemi_office_name": (
                        company_data.gemiOffice.descr
                        if company_data.gemiOffice
                        else None
                    ),
                    "incorporation_date": company_data.incorporationDate,
                    "last_status_change": company_data.lastStatusChange,
                    "status_id": (
                        company_data.status.id if company_data.status else None
                    ),
                    "status_name": (
                        company_data.status.descr if company_data.status else None
                    ),
                    "auto_registered": company_data.autoRegistered,
                    "branch_gemi_numbers": company_data.branch or [],
                    # 'discovered_via_afm': discovered_via_afm or company.discovered_via_afm,
                    # 'search_rank': search_rank or company.search_rank,
                    "last_updated": timezone.now(),
                },
            )

            # Save related data
            cls._save_company_activities(company, company_data.activities or [])
            cls._save_company_persons(company, company_data.persons or [])
            cls._save_company_capital(company, company_data.capital or [])
            cls._save_company_stocks(company, company_data.stocks or [])

            logger.info(
                f"{'Created' if created else 'Updated'} company {company.ar_gemi} in database"
            )
            return company

        except Exception as e:
            logger.error(f"Error saving company {company_data.arGemi} to database: {e}")
            raise

    @classmethod
    def _save_company_activities(cls, company: Company, activities: list):
        """Save company activities."""
        # Clear existing activities
        CompanyActivity.objects.filter(company=company).delete()

        for activity_data in activities:
            CompanyActivity.objects.create(
                company=company,
                activity_id=activity_data.activity.id,
                activity_name=activity_data.activity.descr,
                activity_type=activity_data.type,
                date_from=activity_data.dtFrom,
                date_to=activity_data.dtTo,
            )

    @classmethod
    def _save_company_persons(cls, company: Company, persons: list):
        """Save company persons."""
        # Clear existing persons
        CompanyPerson.objects.filter(company=company).delete()

        for person_data in persons:
            CompanyPerson.objects.create(
                company=company,
                person_name=person_data.personName,
                business_name=person_data.businessName,
                role=person_data.role,
                date_from=person_data.dtFrom,
                date_to=person_data.dtTo,
                is_representative_alone=person_data.isRepresentativeAlone,
                is_representative_in_common=person_data.isRepresentativeInCommon,
            )

    @classmethod
    def _save_company_capital(cls, company: Company, capital: list):
        """Save company capital."""
        # Clear existing capital
        CompanyCapital.objects.filter(company=company).delete()

        for capital_data in capital:
            CompanyCapital.objects.create(
                company=company,
                capital_stock=capital_data.capitalStock,
                currency=capital_data.currency,
                ecsokefalaiikes=capital_data.ecsokefalaiikes,
                eggiitikes=capital_data.eggiitikes,
            )

    @classmethod
    def _save_company_stocks(cls, company: Company, stocks: list):
        """Save company stocks."""
        # Clear existing stocks
        CompanyStock.objects.filter(company=company).delete()

        for stock_data in stocks:
            CompanyStock.objects.create(
                company=company,
                stock_type_id=stock_data.stockTypeId,
                amount=stock_data.amount,
                nominal_price=stock_data.nominalPrice,
                stock_type=stock_data.stockType,
            )
