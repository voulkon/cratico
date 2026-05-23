import re
from datetime import datetime
from io import StringIO

from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.http import JsonResponse
from loguru import logger


@staff_member_required
def fetch_daily_decisions(request):
    """Admin view to trigger fetching decisions for a specific day using the management command"""
    if request.method == "POST":
        target_date_str = request.POST.get("date")
        force = request.POST.get("force", "false").lower() == "true"
        reconcile = (
            request.POST.get("reconcile", "true").lower() == "true"
        )  # Default to true
        distributed = request.POST.get("distributed", "false").lower() == "true"
        incremental = request.POST.get("incremental", "false").lower() == "true"

        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return JsonResponse(
                {"success": False, "error": "Invalid date format"}, status=400
            )

        try:
            # Build command arguments
            cmd_args = ["--date", target_date.isoformat()]

            if force:
                cmd_args.append("--force")
            if reconcile and not incremental:  # Reconcile doesn't apply to incremental
                cmd_args.append("--reconcile")
            if distributed and not incremental:  # Distributed only for daily sync
                cmd_args.append("--distributed")
            if incremental:
                cmd_args.append("--incremental")

            # Capture command output
            output = StringIO()

            # Execute the management command (now creates ImportJob automatically)
            call_command("import_decisions_daily", *cmd_args, stdout=output)

            command_output = output.getvalue()

            # Parse output for key information
            processed_count = "N/A"
            log_file = None
            task_id = None
            import_job_id = None

            for line in command_output.split("\n"):
                if "Processed" in line or "processed" in line:
                    # Try to extract count
                    match = re.search(r"(\d+)\s+decisions", line)
                    if match:
                        processed_count = match.group(1)
                if "ImportJob #" in line:
                    # Extract ImportJob ID
                    match = re.search(r"ImportJob #(\d+)", line)
                    if match:
                        import_job_id = match.group(1)
                if "Logs" in line or "logs" in line or "log_file" in line.lower():
                    # Extract log file path
                    match = re.search(r"/code/logs/[^\s]+", line)
                    if match:
                        log_file = match.group(0)
                if "task ID" in line or "Task ID" in line:
                    # Extract Celery task ID for distributed mode
                    match = re.search(
                        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                        line,
                    )
                    if match:
                        task_id = match.group(0)

            response_data = {
                "success": True,
                "message": f"Successfully initiated import for {target_date}",
                "date": target_date.isoformat(),
                "processed_count": processed_count,
                "command_output": command_output,
                "options": {
                    "force": force,
                    "reconcile": reconcile,
                    "distributed": distributed,
                    "incremental": incremental,
                },
            }

            if import_job_id:
                response_data["import_job_id"] = import_job_id
                response_data["import_job_url"] = (
                    f"/api/admin/core/importjob/{import_job_id}/change/"
                )
                response_data["message"] += f" (ImportJob #{import_job_id})"
            if log_file:
                response_data["log_file"] = log_file
            if task_id:
                response_data["task_id"] = task_id
                response_data["message"] = (
                    f"Distributed import dispatched for {target_date}. Task ID: {task_id}"
                )

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(
                f"Error executing import command for {target_date}: {str(e)}",
                exc_info=True,
            )
            return JsonResponse(
                {"success": False, "error": f"Failed to execute import: {str(e)}"},
                status=500,
            )

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)
