from datetime import date, datetime, timedelta

from core.services.decision_analysis_service import DecisionAnalysisService
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from loguru import logger


@staff_member_required
def daily_decision_analysis(request):
    """Admin view for analyzing daily decision composition"""
    # Get target date from request
    date_param = request.GET.get("date", "")

    try:
        if date_param:
            target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
        else:
            target_date = date.today() - timedelta(days=1)  # Default to yesterday
    except ValueError:
        target_date = date.today() - timedelta(days=1)

    # Get mode parameter - default to 'simple' for fast loading
    mode = request.GET.get("mode", "simple")

    # Initialize analysis service
    analysis_service = DecisionAnalysisService()

    # Calculate navigation dates
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)

    # Don't allow future dates
    if next_date > date.today():
        next_date = None

    if mode == "simple":
        # Fast lightweight view - only 3 queries
        logger.debug(f"Loading simple view for {target_date}")
        analysis_data = analysis_service.get_daily_decision_quick_summary(target_date)

        context = {
            "target_date": target_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "analysis": analysis_data,
            "mode": "simple",
        }

        return render(request, "admin/daily_decision_simple.html", context)

    else:
        # Full analytical view - 15+ queries
        logger.debug(f"Loading analytical view for {target_date}")

        # Get pagination parameters
        try:
            offset = int(request.GET.get("offset", 0))
            limit = int(request.GET.get("limit", 10))
        except ValueError:
            offset = 0
            limit = 10

        # Get filter parameters
        decision_type_uid = request.GET.get("decision_type_uid")

        # Get comprehensive analysis
        analysis_data = analysis_service.get_daily_decision_analysis(target_date)

        # Get paginated decision details
        decision_details = analysis_service.get_daily_decisions_with_details(
            target_date, offset, limit, decision_type_uid=decision_type_uid
        )

        context = {
            "target_date": target_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "analysis": analysis_data,
            "decision_details": decision_details,
            "current_offset": offset,
            "current_limit": limit,
            "current_decision_type_uid": decision_type_uid,
            "mode": "analytical",
        }

        return render(request, "admin/daily_decision_analysis.html", context)


@staff_member_required
def decision_analysis_api(request):
    """JSON API endpoint for decision analysis data"""
    target_date_str = request.GET.get("date")
    comparison_dates = request.GET.getlist("compare_dates")

    analysis_service = DecisionAnalysisService()

    try:
        if target_date_str:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            analysis_data = analysis_service.get_daily_decision_analysis(target_date)
        elif comparison_dates:
            # Compare multiple dates
            dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in comparison_dates]
            analysis_data = analysis_service.compare_daily_patterns(dates)
        else:
            # Default to yesterday
            target_date = date.today() - timedelta(days=1)
            analysis_data = analysis_service.get_daily_decision_analysis(target_date)

        return JsonResponse(analysis_data, safe=False)

    except ValueError as e:
        return JsonResponse({"error": f"Invalid date format: {str(e)}"}, status=400)
    except Exception as e:
        logger.error(f"Decision analysis API error: {str(e)}")
        return JsonResponse({"error": "Internal server error"}, status=500)
