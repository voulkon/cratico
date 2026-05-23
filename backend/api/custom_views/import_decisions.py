from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from loguru import logger


@csrf_exempt
@require_POST
@staff_member_required
def calendar_bulk_import(request):
    """
    Admin view for importing decisions from a calendar date range selection.

    Expects POST data with:
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - entity_type: 'organization', 'unit', or 'signer'
    - entity_id: ID of the organization, unit, or signer
    """
    try:
        # Parse request data
        start_date_str = request.POST.get("start_date")
        end_date_str = request.POST.get("end_date")
        entity_type = request.POST.get("entity_type")
        entity_id = request.POST.get("entity_id")

        if not all([start_date_str, end_date_str, entity_type, entity_id]):
            return JsonResponse(
                {"success": False, "error": "Missing required parameters"}, status=400
            )

        # Parse dates
        start_date = datetime.fromisoformat(start_date_str).date()
        end_date = datetime.fromisoformat(end_date_str).date()

        # Build search params based on entity selection
        search_params = {}
        if entity_type == "organization":
            search_params["org"] = entity_id
        elif entity_type == "unit":
            search_params["unit"] = entity_id
        elif entity_type == "signer":
            search_params["signer"] = entity_id

        # Use the ImportJobQueue to manage concurrency and prevent Redis overload
        # This ensures only MAX_CONCURRENT_JOBS run simultaneously
        try:
            from core.services.import_job_queue import ImportJobQueue

            queue = ImportJobQueue()

            # Queue one job per day in the range
            queued_jobs = []
            current_date = start_date

            while current_date <= end_date:
                # Queue job (will auto-dispatch if capacity available)
                job = queue.enqueue_job(
                    target_date=current_date,
                    search_params=search_params,
                    created_by=request.user,
                    organization_id=(
                        entity_id if entity_type == "organization" else None
                    ),
                    unit_id=entity_id if entity_type == "unit" else None,
                    signer_id=entity_id if entity_type == "signer" else None,
                    auto_dispatch=True,  # Auto-dispatch if capacity available
                )

                queued_jobs.append(
                    {
                        "date": current_date.isoformat(),
                        "job_id": job.id,
                        "status": job.status,
                    }
                )

                logger.info(
                    f"Coverage Explorer: Queued import for {current_date} "
                    f"({entity_type} {entity_id}), ImportJob #{job.id}, Status: {job.status}"
                )

                current_date += timedelta(days=1)

            # Get queue status for user feedback
            queue_status = queue.get_queue_status()

            # Return success with queued jobs
            return JsonResponse(
                {
                    "success": True,
                    "jobs": queued_jobs,
                    "count": len(queued_jobs),
                    "queue_status": queue_status,
                    "message": (
                        f"Queued {len(queued_jobs)} import jobs for {entity_type} {entity_id} "
                        f"from {start_date_str} to {end_date_str}. "
                        f'Jobs will run sequentially (max {queue_status["max_concurrent"]} concurrent).'
                    ),
                }
            )

        except Exception as e:
            logger.error(f"Coverage Explorer import failed: {str(e)}")
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
