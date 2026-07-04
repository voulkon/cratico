import calendar
from datetime import date, timedelta

from core.models.import_jobs import DateCoverage
from core.models.organizations import Organization, Signer, Unit


def get_month_calendar_data(month, year, entity_type, entity_id):
    """Generate calendar data for a specific month including decision counts"""
    # Get first and last day of the month
    first_day = date(year, month, 1)
    # Last day is first day of next month - 1 day
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    # Get calendar info
    calendar.monthcalendar(year, month)

    # Get decision coverage data
    coverage_data = {}
    if entity_type == "all":
        # For "all" decisions, use indexed date columns for fast aggregation
        from core.models.decisions import Decision
        from django.db.models import Count

        # issue_date_day is already a full date, so filter and group by it directly
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        decisions_by_day = (
            Decision.objects.filter_by_date_range(first_day, last_day)
            .values("issue_date_day")
            .annotate(count=Count("id"))
            .order_by("issue_date_day")
        )

        # issue_date_day is already a date object
        for item in decisions_by_day:
            day_date = item["issue_date_day"]
            if day_date:
                coverage_data[day_date] = item["count"]
    elif entity_id:
        # Get the date coverage for the selected entity
        coverage_query = DateCoverage.objects.filter(date__year=year, date__month=month)

        if entity_type == "organization":
            coverage_query = coverage_query.filter(organization_id=entity_id)
        else:
            coverage_query = coverage_query.filter(signer_id=entity_id)

        # Create lookup by date
        for coverage in coverage_query:
            coverage_data[coverage.date] = coverage.decision_count

    # Build calendar data
    calendar_data = []

    # Add days from previous month to fill first week
    first_weekday = first_day.weekday()  # Monday is 0, Sunday is 6
    first_weekday = (first_weekday + 1) % 7  # Convert to Sunday is 0

    if first_weekday > 0:
        # Calculate days from previous month
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year -= 1

        prev_month_days = calendar.monthrange(prev_year, prev_month)[1]
        for i in range(first_weekday):
            day_num = prev_month_days - first_weekday + i + 1
            calendar_data.append(
                {
                    "day": day_num,
                    "date": date(prev_year, prev_month, day_num).isoformat(),
                    "is_current_month": False,
                    "count": 0,
                    "has_data": False,
                }
            )

    # Add days from current month
    for day in range(1, last_day.day + 1):
        current_date = date(year, month, day)
        count = coverage_data.get(current_date, 0)
        calendar_data.append(
            {
                "day": day,
                "date": current_date.isoformat(),
                "is_current_month": True,
                "count": count,
                "has_data": count > 0,
            }
        )

    # Add days from next month to fill last week
    remaining_days = 42 - len(calendar_data)  # 6 weeks × 7 days = 42
    if remaining_days > 0:
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1

        for day in range(1, remaining_days + 1):
            calendar_data.append(
                {
                    "day": day,
                    "date": date(next_year, next_month, day).isoformat(),
                    "is_current_month": False,
                    "count": 0,
                    "has_data": False,
                }
            )

    return calendar_data


def get_entity_name(entity_type, entity_id):
    """Helper function to get entity name"""
    if entity_type == "all":
        return "All Decisions"

    entity_name = None
    if entity_id:
        try:
            if entity_type == "organization":
                org = Organization.objects.get(uid=entity_id)
                entity_name = org.label
            elif entity_type == "unit":
                unit = Unit.objects.get(uid=entity_id)
                entity_name = unit.label
            else:  # signer
                signer = Signer.objects.get(uid=entity_id)
                entity_name = f"{signer.last_name}, {signer.first_name}"
        except (Organization.DoesNotExist, Unit.DoesNotExist, Signer.DoesNotExist):
            pass
    return entity_name


def get_year_summary_data(year, entity_type, entity_id):
    """Get summary data for a specific year"""
    total_decisions = 0
    months_with_data = 0

    if entity_type == "all":
        # For "all" decisions, use indexed date columns for fast aggregation
        from core.models.decisions import Decision
        from django.db.models import Count

        # issue_date_month is a date (first day of month), filter by year and group by it
        first_day_of_year = date(year, 1, 1)
        last_day_of_year = date(year, 12, 31)

        decisions_by_month = (
            Decision.objects.filter_by_date_range(
                first_day_of_year, last_day_of_year, field="issue_date_month"
            )
            .values("issue_date_month")
            .annotate(count=Count("id"))
            .order_by("issue_date_month")
        )

        total_decisions = sum(item["count"] for item in decisions_by_month)
        months_with_data = len(decisions_by_month)
    elif entity_id:
        # Get coverage data for the entire year
        coverage_query = DateCoverage.objects.filter(date__year=year)

        if entity_type == "organization":
            coverage_query = coverage_query.filter(organization_id=entity_id)
        else:
            coverage_query = coverage_query.filter(signer_id=entity_id)

        # Sum total decisions
        total_decisions = sum(coverage.decision_count for coverage in coverage_query)

        # Count months with data
        months_with_data = coverage_query.values("date__month").distinct().count()

    return {"total_decisions": total_decisions, "months_with_data": months_with_data}
