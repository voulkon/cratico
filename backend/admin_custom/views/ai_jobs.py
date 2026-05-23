import importlib
from datetime import datetime

from core.models.ai_pricing import AIJobDefinition
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, render


@staff_member_required
def estimate_job_cost_view(request, job_id):
    """
    Admin view to estimate cost for a specific job.
    Allows selecting date and other parameters.
    """
    job_def = get_object_or_404(AIJobDefinition, pk=job_id)

    # Default values
    target_date_str = request.GET.get("date", "2025-12-28")  # Default as requested
    provider = request.GET.get("provider", job_def.default_provider)
    model = request.GET.get("model", job_def.default_model)

    context = {
        "job": job_def,
        "target_date": target_date_str,
        "provider": provider,
        "model": model,
        "title": f"Estimate Cost: {job_def.display_name}",
    }

    if request.method == "POST":
        # Get parameters from form
        target_date_str = request.POST.get("date")
        provider = request.POST.get("provider")
        model = request.POST.get("model")

        try:
            # Parse date
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()

            # Import job class dynamically
            module_name = job_def.algorithm_module
            class_name = job_def.algorithm_class

            module = importlib.import_module(module_name)
            JobClass = getattr(module, class_name)

            # Initialize job
            job = JobClass(job_def)

            # Run estimation
            result = job.estimate_cost(
                provider=provider, model=model, target_date=target_date
            )

            # Format numbers for display to avoid template filter issues
            if result.get("total_cost_usd") is not None:
                result["total_cost_usd_formatted"] = f"{result['total_cost_usd']:.6f}"

            if result.get("average_cost_per_item_usd") is not None:
                result["average_cost_per_item_usd_formatted"] = (
                    f"{result['average_cost_per_item_usd']:.6f}"
                )

            if result.get("items"):
                for item in result["items"]:
                    if item.get("cost_usd") is not None:
                        item["cost_usd_formatted"] = f"{item['cost_usd']:.6f}"

            context.update(
                {
                    "result": result,
                    "target_date": target_date_str,
                    "provider": provider,
                    "model": model,
                    "success": True,
                }
            )

        except Exception as e:
            context["error"] = str(e)
            context["success"] = False

    return render(request, "admin/estimate_job_cost.html", context)
