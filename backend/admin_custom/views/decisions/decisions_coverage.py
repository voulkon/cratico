import calendar
from datetime import datetime

from admin_custom.views.common_utils import entity_search_ajax
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from .decisions_utils import (
    get_entity_name,
    get_month_calendar_data,
    get_year_summary_data,
)


@staff_member_required
def coverage_explorer(request):
    """View for exploring decision coverage by organization, unit, signer, or ALL decisions"""
    # Get selected entity
    entity_type = request.GET.get(
        "entity_type", "all"  # Default to 'all' - showing all decisions
    )  # 'all', 'organization', 'unit', or 'signer'
    entity_id = request.GET.get("entity_id")

    # Normalize null/empty entity_id (handle 'null' string from JavaScript)
    if entity_id in ["null", "None", ""]:
        entity_id = None

    # Get view type (quarter, year, or multi-year)
    view_type = request.GET.get("view", "quarter")  # 'quarter', 'year', or 'multi-year'

    # Get the current month or the requested month
    month_param = request.GET.get("month", "")
    year_param = request.GET.get("year", "")

    try:
        month = int(month_param) if month_param else datetime.now().month
    except ValueError:
        month = datetime.now().month

    try:
        year = int(year_param) if year_param else datetime.now().year
    except ValueError:
        year = datetime.now().year

    # Handle entity type validation
    if entity_type not in ["all", "organization", "unit", "signer"]:
        entity_type = "all"  # Default fallback to show all decisions

    if view_type == "multi-year":
        # Create multi-year view (10 years centered around current year)
        start_year = year - 5
        end_year = year + 4

        multi_year_data = []
        for target_year in range(start_year, end_year + 1):
            # Get year summary data
            year_summary = get_year_summary_data(target_year, entity_type, entity_id)
            multi_year_data.append(
                {
                    "year": target_year,
                    "total_decisions": year_summary["total_decisions"],
                    "months_with_data": year_summary["months_with_data"],
                    "has_data": year_summary["total_decisions"] > 0,
                }
            )

        # Calculate navigation links for multi-year view
        prev_decade_year = year - 10
        next_decade_year = year + 10

        context = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": get_entity_name(entity_type, entity_id),
            "view_type": view_type,
            "center_year": year,
            "multi_year_data": multi_year_data,
            "start_year": start_year,
            "end_year": end_year,
            "prev_decade_year": prev_decade_year,
            "next_decade_year": next_decade_year,
        }
    elif view_type == "year":
        # Existing year view logic
        year_calendar = []
        for month_offset in range(12):
            target_month = month_offset + 1
            target_year = year

            month_data = {
                "month": target_month,
                "year": target_year,
                "name": calendar.month_name[target_month],
                "days": get_month_calendar_data(
                    target_month, target_year, entity_type, entity_id
                ),
            }
            year_calendar.append(month_data)

        # Calculate navigation links for year view
        prev_year = year - 1
        next_year = year + 1

        context = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": get_entity_name(entity_type, entity_id),
            "view_type": view_type,
            "year": year,
            "year_calendar": year_calendar,
            "prev_year": prev_year,
            "next_year": next_year,
        }
    else:
        # Existing quarter view logic
        quarter_calendar = []
        for month_offset in range(-1, 2):
            target_month = month + month_offset
            target_year = year

            if target_month < 1:
                target_month += 12
                target_year -= 1
            elif target_month > 12:
                target_month -= 12
                target_year += 1

            month_data = {
                "month": target_month,
                "year": target_year,
                "name": calendar.month_name[target_month],
                "days": get_month_calendar_data(
                    target_month, target_year, entity_type, entity_id
                ),
            }
            quarter_calendar.append(month_data)

        # Calculate navigation links for quarter
        prev_quarter_month = month - 3
        prev_quarter_year = year
        if prev_quarter_month < 1:
            prev_quarter_month += 12
            prev_quarter_year -= 1

        next_quarter_month = month + 3
        next_quarter_year = year
        if next_quarter_month > 12:
            next_quarter_month -= 12
            next_quarter_year += 1

        # Create quarter name
        if month in (1, 2, 3):
            quarter_name = "Q1"
        elif month in (4, 5, 6):
            quarter_name = "Q2"
        elif month in (7, 8, 9):
            quarter_name = "Q3"
        else:
            quarter_name = "Q4"

        quarter_name = f"{quarter_name} {year}"

        context = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": get_entity_name(entity_type, entity_id),
            "view_type": view_type,
            "year": year,
            "quarter_name": quarter_name,
            "quarter_calendar": quarter_calendar,
            "prev_quarter_month": prev_quarter_month,
            "prev_quarter_year": prev_quarter_year,
            "next_quarter_month": next_quarter_month,
            "next_quarter_year": next_quarter_year,
        }

    return render(request, "admin/coverage_explorer.html", context)


@staff_member_required
def entity_search(request):
    """
    Search for organizations, units, or signers for the coverage explorer.
    Delegates to common entity search utility.
    """
    return entity_search_ajax(request)
