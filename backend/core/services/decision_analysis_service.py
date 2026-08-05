from datetime import date
from typing import Any, Dict, List, Optional

from core.models.decisions import Decision
from core.models.entities import DecisionAmountField
from django.db.models import Avg, Count, Max, Min, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, Extract, TruncHour
from loguru import logger


class DecisionAnalysisService:
    """
    Service for analyzing decision data structure and composition.
    Provides reusable logic for admin dashboards and API endpoints.
    """

    publish_date_field_name = "publish_timestamp"

    def get_daily_decision_quick_summary(self, target_date: date) -> Dict[str, Any]:
        """
        Get lightweight summary of decisions for a specific day.
        Only essential metrics - much faster than full analysis.

        Args:
            target_date: Date to analyze

        Returns:
            Dictionary with basic metrics (3 queries instead of 15+)
        """
        logger.info(f"Quick summary for {target_date}")

        # Base queryset for the target date
        decisions_qs = Decision.objects.filter(issue_date_day=target_date)
        total_count = decisions_qs.count()

        # Get day of week info
        day_of_week = target_date.strftime("%A")
        is_weekend = target_date.weekday() >= 5

        if total_count == 0:
            return {
                "date": target_date,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "total_count": 0,
                "has_data": False,
                "message": f"No decisions found for {target_date} ({day_of_week})",
            }

        # Just top 5 types and orgs - single optimized query each
        top_types = list(
            decisions_qs.values("decision_type__label", "decision_type__uid")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )

        top_orgs = list(
            decisions_qs.values("organization__label", "organization__uid")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )

        # Quick content check - single query
        content_counts = decisions_qs.aggregate(
            with_subject=Count(
                "id", filter=~Q(subject__isnull=True) & ~Q(subject__exact="")
            ),
            with_documents=Count(
                "id", filter=~Q(document_url__isnull=True) & ~Q(document_url__exact="")
            ),
        )

        return {
            "date": target_date,
            "day_of_week": day_of_week,
            "is_weekend": is_weekend,
            "total_count": total_count,
            "has_data": True,
            "top_types": top_types,
            "top_organizations": top_orgs,
            "with_subject": content_counts["with_subject"],
            "with_documents": content_counts["with_documents"],
            "subject_coverage": (
                round(content_counts["with_subject"] / total_count * 100, 1)
                if total_count > 0
                else 0
            ),
            "document_coverage": (
                round(content_counts["with_documents"] / total_count * 100, 1)
                if total_count > 0
                else 0
            ),
        }

    def get_daily_decision_analysis(self, target_date: date) -> Dict[str, Any]:
        """
        Get comprehensive analysis of decisions for a specific day.

        Args:
            target_date: Date to analyze

        Returns:
            Dictionary with various analysis metrics
        """
        logger.info(f"Analyzing decisions for {target_date}")

        # Base queryset for the target date
        decisions_qs = Decision.objects.filter(issue_date_day=target_date)
        total_count = decisions_qs.count()

        # Get day of week info
        day_of_week = target_date.strftime("%A")  # Full day name (e.g., "Monday")
        is_weekend = target_date.weekday() >= 5  # Saturday=5, Sunday=6

        if total_count == 0:
            return {
                "date": target_date,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "total_count": 0,
                "has_data": False,
                "message": f"No decisions found for {target_date} ({day_of_week})",
            }

        # Get all analysis components
        analysis = {
            "date": target_date,
            "day_of_week": day_of_week,
            "is_weekend": is_weekend,
            "total_count": total_count,
            "has_data": True,
            # Basic composition
            "by_type": self._analyze_by_type(decisions_qs),
            "by_organization": self._analyze_by_organization(decisions_qs),
            "by_signer": self._analyze_by_signer(decisions_qs),
            # Temporal patterns
            "by_hour": self._analyze_by_hour(decisions_qs),
            "timing_stats": self._get_timing_stats(decisions_qs),
            # Content analysis
            "content_stats": self._get_content_stats(decisions_qs),
            # Document analysis
            "document_stats": self._get_document_stats(decisions_qs),
            # Top entities
            "top_organizations": self._get_top_organizations(decisions_qs, limit=10),
            "top_signers": self._get_top_signers(decisions_qs, limit=10),
            "top_types": self._get_top_types(decisions_qs, limit=10),
            # Quality indicators
            "quality_indicators": self._get_quality_indicators(decisions_qs),
            # Financial summary
            "financial_summary": self._get_financial_summary(decisions_qs),
        }

        return analysis

    def _analyze_by_type(self, decisions_qs) -> List[Dict[str, Any]]:
        """Analyze decisions by act type"""
        # Subquery to get calculated amount for a decision
        # Sum all amounts from DecisionAmountField (linked or not)
        calc_amt_subquery = Subquery(
            DecisionAmountField.objects.filter(decision=OuterRef("pk"))
            .values("decision")
            .annotate(total=Sum("amount"))
            .values("total")
        )

        return list(
            decisions_qs.annotate(eff_amt=Coalesce("amount", calc_amt_subquery))
            .values("decision_type__label", "decision_type__uid")
            .annotate(count=Count("id"), total_amount=Sum("eff_amt"))
            .order_by("-count")
        )

    def _analyze_by_organization(self, decisions_qs) -> List[Dict[str, Any]]:
        """Analyze decisions by organization"""
        return list(
            decisions_qs.values("organization__label", "organization__uid")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

    def _analyze_by_signer(self, decisions_qs) -> List[Dict[str, Any]]:
        """Analyze decisions by signer"""
        return list(
            decisions_qs.values(
                "signers__first_name", "signers__last_name", "signers__uid"
            )
            .annotate(count=Count("id"))
            .order_by("-count")
        )

    def _analyze_by_hour(self, decisions_qs) -> List[Dict[str, Any]]:
        """Analyze decisions by hour of day"""
        return list(
            decisions_qs.annotate(hour=TruncHour(self.publish_date_field_name))
            .values("hour")
            .annotate(count=Count("id"))
            .order_by("hour")
        )

    def _get_timing_stats(self, decisions_qs) -> Dict[str, Any]:
        """Get timing statistics for decisions"""
        stats = decisions_qs.aggregate(
            earliest=Min(self.publish_date_field_name),
            latest=Max(self.publish_date_field_name),
        )

        # Calculate average hour separately using Extract
        avg_hour_stats = decisions_qs.aggregate(
            avg_hour=Avg(Extract(self.publish_date_field_name, "hour"))
        )

        return {
            "earliest_time": stats["earliest"],
            "latest_time": stats["latest"],
            "avg_hour": avg_hour_stats["avg_hour"],
            "time_span_hours": (
                (stats["latest"] - stats["earliest"]).total_seconds() / 3600
                if stats["earliest"] and stats["latest"]
                else 0
            ),
        }

    def _get_content_stats(self, decisions_qs) -> Dict[str, Any]:
        """Analyze content characteristics"""
        # Get decisions with subject/document_url data
        with_subject = decisions_qs.exclude(
            Q(subject__isnull=True) | Q(subject__exact="")
        )
        with_documents = decisions_qs.exclude(
            Q(document_url__isnull=True) | Q(document_url__exact="")
        )

        return {
            "with_subject": with_subject.count(),
            "with_documents": with_documents.count(),
            "subject_coverage": round(
                with_subject.count() / decisions_qs.count() * 100, 1
            ),
            "document_coverage": round(
                with_documents.count() / decisions_qs.count() * 100, 1
            ),
        }

    def _get_document_stats(self, decisions_qs) -> Dict[str, Any]:
        """Analyze document extraction status"""
        from core.models.document_analysis import DocumentExtraction, ProcessingStatus

        # Get extraction stats for decisions with documents
        decisions_with_docs = decisions_qs.exclude(
            Q(document_url__isnull=True) | Q(document_url__exact="")
        )

        if decisions_with_docs.count() == 0:
            return {
                "total_with_docs": 0,
                "extracted": 0,
                "pending": 0,
                "failed": 0,
                "extraction_rate": 0,
            }

        # Count extractions by status
        extracted = DocumentExtraction.objects.filter(
            decision__in=decisions_with_docs,
            extraction_status=ProcessingStatus.COMPLETED,
        ).count()

        pending = DocumentExtraction.objects.filter(
            decision__in=decisions_with_docs,
            extraction_status__in=[
                ProcessingStatus.PENDING,
                ProcessingStatus.PROCESSING,
                ProcessingStatus.NEEDS_VISION,
            ],
        ).count()

        failed = DocumentExtraction.objects.filter(
            decision__in=decisions_with_docs, extraction_status=ProcessingStatus.FAILED
        ).count()

        total_with_docs = decisions_with_docs.count()

        return {
            "total_with_docs": total_with_docs,
            "extracted": extracted,
            "pending": pending,
            "failed": failed,
            "extraction_rate": (
                round(extracted / total_with_docs * 100, 1)
                if total_with_docs > 0
                else 0
            ),
        }

    def _get_top_organizations(
        self, decisions_qs, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get top organizations by decision count"""
        return list(
            decisions_qs.values("organization__label", "organization__uid")
            .annotate(count=Count("id"))
            .order_by("-count")[:limit]
        )

    def _get_top_signers(self, decisions_qs, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top signers by decision count"""
        return list(
            decisions_qs.values(
                "signers__first_name", "signers__last_name", "signers__uid"
            )
            .annotate(count=Count("id"))
            .order_by("-count")[:limit]
        )

    def _get_top_types(self, decisions_qs, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top decision types by count"""
        return list(
            decisions_qs.values("decision_type__label", "decision_type__uid")
            .annotate(count=Count("id"))
            .order_by("-count")[:limit]
        )

    def _get_quality_indicators(self, decisions_qs) -> Dict[str, Any]:
        """Calculate data quality indicators"""
        total = decisions_qs.count()

        # Count decisions with various quality issues
        missing_subject = decisions_qs.filter(
            Q(subject__isnull=True) | Q(subject__exact="")
        ).count()
        missing_org = decisions_qs.filter(organization__isnull=True).count()
        no_signers = decisions_qs.filter(signers__isnull=True).count()
        missing_type = decisions_qs.filter(decision_type__isnull=True).count()

        return {
            "completeness_score": (
                round(
                    (total - missing_subject - missing_org - no_signers - missing_type)
                    / (total)
                    * 100,
                    1,
                )
                if total > 0
                else 0
            ),
            "missing_subject_count": missing_subject,
            "missing_organization_count": missing_org,
            "no_signers_count": no_signers,
            "missing_type_count": missing_type,
        }

    def _get_financial_summary(self, decisions_qs) -> Dict[str, Any]:
        """Calculate financial summaries by various entities"""
        from core.models.entities import (
            DecisionAmountField,
            DecisionEntityRelationship,
            EntityRole,
        )
        from django.db.models import OuterRef, Subquery, Sum
        from django.db.models.functions import Coalesce

        # Subquery to get calculated amount for a decision
        calc_amt_subquery = Subquery(
            DecisionAmountField.objects.filter(decision=OuterRef("pk"))
            .values("decision")
            .annotate(total=Sum("amount"))
            .values("total")
        )

        # Annotate decisions with effective amount
        decisions_with_amount = decisions_qs.annotate(
            effective_amt=Coalesce("amount", calc_amt_subquery)
        )

        # Total amount for the day
        total_amount = (
            decisions_with_amount.aggregate(total=Sum("effective_amt"))["total"] or 0
        )

        # Amounts by organization
        by_org = list(
            decisions_with_amount.values("organization__label")
            .annotate(total_amount=Sum("effective_amt"))
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[:5]
        )

        # Amounts by signer
        by_signer = list(
            decisions_with_amount.values("signers__first_name", "signers__last_name")
            .annotate(total_amount=Sum("effective_amt"))
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[:5]
        )

        # Amounts by sponsor (counterpart)
        # Get the amounts from DecisionAmountField through relationships
        by_sponsor = list(
            DecisionEntityRelationship.objects.filter(
                decision__in=decisions_qs, role=EntityRole.SPONSOR
            )
            .values("entity__name", "entity__afm")
            .annotate(total_amount=Sum("linked_amounts__amount"))
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[:5]
        )

        return {
            "total_amount": float(total_amount),
            "by_organization": by_org,
            "by_signer": by_signer,
            "by_sponsor": by_sponsor,
        }

    def get_date_range_analysis(
        self,
        start_date: date,
        end_date: date,
        group_by: str = "day",  # 'day', 'week', 'month'
    ) -> Dict[str, Any]:
        """
        Get analysis for a date range with grouping.
        Useful for trends and comparisons.
        """
        logger.info(
            f"Analyzing decisions from {start_date} to {end_date}, grouped by {group_by}"
        )

        decisions_qs = Decision.objects.filter(
            issue_date_day__gte=start_date, issue_date_day__lte=end_date
        )

        # Group by time period
        if group_by == "day":
            from django.db.models.functions import TruncDate

            grouped_data = (
                decisions_qs.annotate(period=TruncDate("issue_date"))
                .values("period")
                .annotate(count=Count("id"))
                .order_by("period")
            )
        elif group_by == "week":
            from django.db.models.functions import TruncWeek

            grouped_data = (
                decisions_qs.annotate(period=TruncWeek("issue_date"))
                .values("period")
                .annotate(count=Count("id"))
                .order_by("period")
            )
        elif group_by == "month":
            from django.db.models.functions import TruncMonth

            grouped_data = (
                decisions_qs.annotate(period=TruncMonth("issue_date"))
                .values("period")
                .annotate(count=Count("id"))
                .order_by("period")
            )
        else:
            raise ValueError(f"Invalid group_by value: {group_by}")

        return {
            "start_date": start_date,
            "end_date": end_date,
            "group_by": group_by,
            "total_decisions": decisions_qs.count(),
            "grouped_data": list(grouped_data),
            "summary": self._get_range_summary(decisions_qs),
        }

    def _get_range_summary(self, decisions_qs) -> Dict[str, Any]:
        """Get summary stats for a decision queryset"""
        return {
            "total_count": decisions_qs.count(),
            "unique_organizations": decisions_qs.values("organization")
            .distinct()
            .count(),
            "unique_types": decisions_qs.values("decision_type").distinct().count(),
            "unique_signers": decisions_qs.values("signers").distinct().count(),
        }

    def compare_daily_patterns(self, dates: List[date]) -> Dict[str, Any]:
        """
        Compare decision patterns across multiple specific dates.
        Useful for understanding variations.
        """
        logger.info(f"Comparing decision patterns for {len(dates)} dates")

        comparisons = []
        for target_date in dates:
            daily_analysis = self.get_daily_decision_analysis(target_date)
            comparisons.append(
                {
                    "date": target_date,
                    "day_of_week": target_date.strftime("%A"),
                    "is_weekend": target_date.weekday() >= 5,
                    "total_count": daily_analysis["total_count"],
                    "top_organization": (
                        daily_analysis["top_organizations"][0]
                        if daily_analysis["top_organizations"]
                        else None
                    ),
                    "top_type": (
                        daily_analysis["top_types"][0]
                        if daily_analysis["top_types"]
                        else None
                    ),
                    "quality_score": daily_analysis["quality_indicators"][
                        "completeness_score"
                    ],
                    "extraction_rate": daily_analysis["document_stats"][
                        "extraction_rate"
                    ],
                }
            )

        return {
            "dates": dates,
            "comparisons": comparisons,
            "avg_daily_count": (
                sum(c["total_count"] for c in comparisons) / len(comparisons)
                if comparisons
                else 0
            ),
            "max_daily_count": (
                max(c["total_count"] for c in comparisons) if comparisons else 0
            ),
            "min_daily_count": (
                min(c["total_count"] for c in comparisons) if comparisons else 0
            ),
            "weekend_days": sum(1 for c in comparisons if c["is_weekend"]),
            "weekday_avg": (
                sum(c["total_count"] for c in comparisons if not c["is_weekend"])
                / sum(1 for c in comparisons if not c["is_weekend"])
                if any(not c["is_weekend"] for c in comparisons)
                else 0
            ),
            "weekend_avg": (
                sum(c["total_count"] for c in comparisons if c["is_weekend"])
                / sum(1 for c in comparisons if c["is_weekend"])
                if any(c["is_weekend"] for c in comparisons)
                else 0
            ),
        }

    def get_daily_decisions_with_details(
        self,
        target_date: date,
        offset: int = 0,
        limit: int = 10,
        decision_type_uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get paginated decisions for a specific day with detailed information including
        title, signer, company, and DocumentExtraction content.

        Args:
            target_date: Date to fetch decisions for
            offset: Pagination offset
            limit: Number of decisions to return
            decision_type_uid: Optional filter by decision type UID

        Returns:
            Dictionary with decisions and pagination info
        """
        from django.db.models import F

        logger.info(
            f"Fetching detailed decisions for {target_date} (offset: {offset}, limit: {limit}, type: {decision_type_uid})"
        )

        # Base queryset for the target date with related data
        decisions_qs = Decision.objects.filter(issue_date_day=target_date)

        if decision_type_uid:
            decisions_qs = decisions_qs.filter(decision_type__uid=decision_type_uid)

        # Annotate with calculated amount for sorting and display
        # Include all amount fields, not just those linked to relationships
        # (linking is optional for decisions without entities)
        from core.services.decision_facets import amount_sum_excluding_kae

        decisions_qs = decisions_qs.annotate(
            calculated_amount=amount_sum_excluding_kae()
        ).annotate(effective_amount=Coalesce("amount", "calculated_amount"))

        decisions_qs = (
            decisions_qs.select_related(
                "organization", "decision_type", "text_extraction"
            )
            .prefetch_related("signers", "units", "entity_relationships__entity")
            .order_by(F("effective_amount").desc(nulls_last=True), "-issue_date")
        )

        total_count = decisions_qs.count()

        # Get paginated decisions
        decisions = decisions_qs[offset : offset + limit]

        from core.models.companies import Company

        # Prepare decision details
        decision_details = []
        for decision in decisions:
            # Get organization details
            org_info = None
            if decision.organization:
                org_info = {
                    "label": decision.organization.label,
                    "uid": decision.organization.uid,
                    "vat_number": decision.organization.vat_number,
                    "website": decision.organization.website,
                }

            # Get signers details
            signers_info = []
            for signer in decision.signers.all():
                signers_info.append(
                    {
                        "first_name": signer.first_name,
                        "last_name": signer.last_name,
                        "uid": signer.uid,
                    }
                )

            # Get counterparts (companies and people)
            counterparts = []

            for rel in decision.entity_relationships.all():
                entity = rel.entity
                counterpart = {
                    "afm": entity.afm,
                    "name": entity.name,
                    "type": entity.entity_type,
                    "role": rel.get_role_display(),
                    "companies": [],
                }

                # If it's a company or we have an AFM, try to find GEMI data
                if entity.afm:
                    companies = Company.objects.filter(afm=entity.afm).prefetch_related(
                        "persons"
                    )
                    for company in companies:
                        company_info = {
                            "name": company.co_name_el,
                            "gemi": company.ar_gemi,
                            "status": company.status_name,
                            "persons": [
                                {"name": p.person_name, "role": p.role}
                                for p in company.persons.all()
                            ],
                        }
                        counterpart["companies"].append(company_info)

                counterparts.append(counterpart)

            # Get DocumentExtraction content
            extraction_content = None
            if hasattr(decision, "text_extraction") and decision.text_extraction:
                extraction_content = decision.text_extraction.full_text

            # Use effective amount from annotation if available, otherwise fallback
            if (
                hasattr(decision, "effective_amount")
                and decision.effective_amount is not None
            ):
                amount_val = float(decision.effective_amount)
            else:
                amount_val = float(decision.amount) if decision.amount else None

            decision_details.append(
                {
                    "ada": decision.ada,
                    "subject": decision.subject,
                    "protocol_number": decision.protocol_number,
                    "issue_date": decision.issue_date,
                    "organization": org_info,
                    "signers": signers_info,
                    "counterparts": counterparts,
                    "decision_type": (
                        decision.decision_type.label if decision.decision_type else None
                    ),
                    "status": decision.status,
                    "document_url": decision.document_url,
                    "content_preview": (
                        extraction_content[:500] + "..."
                        if extraction_content and len(extraction_content) > 500
                        else extraction_content
                    ),
                    "full_text": extraction_content,
                    "has_private_data": decision.has_private_data,
                    "financial_year": decision.financial_year,
                    "amount": amount_val,
                }
            )

        return {
            "decisions": decision_details,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "has_next": offset + limit < total_count,
            "has_previous": offset > 0,
            "next_offset": offset + limit if offset + limit < total_count else None,
            "previous_offset": offset - limit if offset > 0 else None,
        }
