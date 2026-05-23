"""Custom admin views for managing search suggestions"""

from admin_custom.views.common_utils import entity_search_ajax, get_entity_display_name
from core.models import SearchSuggestion
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Max
from django.shortcuts import redirect, render
from loguru import logger


@staff_member_required
def search_suggestion_manager(request):
    """
    User-friendly interface for managing search suggestions.
    Shows existing suggestions and allows adding new ones with entity search.
    """
    if request.method == "POST":
        # Handle adding a new suggestion
        suggestion_type = request.POST.get("suggestion_type")
        entity_id = request.POST.get("entity_id")
        order_input = request.POST.get("order", "").strip()
        is_active = request.POST.get("is_active") == "on"
        description = request.POST.get("description", "")

        if suggestion_type and entity_id:
            try:
                # Verify entity exists and get name
                entity_name = get_entity_display_name(suggestion_type, entity_id)

                if not entity_name:
                    messages.error(request, "Entity not found")
                    return redirect("admin:search_suggestion_manager")

                # Auto-increment order if not specified
                if not order_input:
                    max_order = SearchSuggestion.objects.aggregate(Max("order"))[
                        "order__max"
                    ]
                    order = (max_order or 0) + 1
                else:
                    order = int(order_input)

                    # Check if order already exists
                    if SearchSuggestion.objects.filter(order=order).exists():
                        messages.warning(
                            request,
                            f"Order {order} already exists. Auto-adjusting to next available order.",
                        )
                        # Find next available order
                        existing_orders = set(
                            SearchSuggestion.objects.values_list("order", flat=True)
                        )
                        while order in existing_orders:
                            order += 1

                # Create the suggestion
                SearchSuggestion.objects.create(
                    suggestion_type=suggestion_type,
                    entity_id=entity_id,
                    order=order,
                    is_active=is_active,
                    description=description,
                )

                messages.success(
                    request,
                    f'Successfully added suggestion for "{entity_name}" with order {order}',
                )
                return redirect("admin:search_suggestion_manager")

            except ValueError:
                messages.error(request, "Invalid order number")
            except Exception as e:
                logger.error(f"Error creating search suggestion: {e}")
                messages.error(request, f"Error: {str(e)}")
        else:
            messages.error(request, "Please select both entity type and entity")

    # Get existing suggestions
    suggestions = SearchSuggestion.objects.all().order_by("order", "-click_count")

    context = {
        "title": "Search Suggestion Manager",
        "suggestions": suggestions,
        "suggestion_types": SearchSuggestion.SUGGESTION_TYPES,
    }

    return render(request, "admin/search_suggestion_manager.html", context)


@staff_member_required
def search_suggestion_entity_search(request):
    """
    AJAX endpoint for searching entities.
    Delegates to common entity search utility.
    """
    return entity_search_ajax(request)


@staff_member_required
def move_suggestion_up(request, pk):
    """Move a suggestion up in order (decrease order number)"""
    if request.method == "POST":
        try:
            suggestion = SearchSuggestion.objects.get(pk=pk)
            current_order = suggestion.order

            # Find the suggestion with the next lower order
            previous_suggestion = (
                SearchSuggestion.objects.filter(order__lt=current_order)
                .order_by("-order")
                .first()
            )

            if previous_suggestion:
                # Swap orders
                temp_order = -999999  # Temporary order to avoid conflicts
                suggestion.order = temp_order
                suggestion.save(update_fields=["order"])

                previous_order = previous_suggestion.order
                previous_suggestion.order = current_order
                previous_suggestion.save(update_fields=["order"])

                suggestion.order = previous_order
                suggestion.save(update_fields=["order"])

                messages.success(request, "Suggestion moved up")
            else:
                messages.info(request, "Already at the top")

        except SearchSuggestion.DoesNotExist:
            messages.error(request, "Suggestion not found")
        except Exception as e:
            logger.error(f"Error moving suggestion up: {e}")
            messages.error(request, f"Error: {str(e)}")

    return redirect("admin:search_suggestion_manager")


@staff_member_required
def move_suggestion_down(request, pk):
    """Move a suggestion down in order (increase order number)"""
    if request.method == "POST":
        try:
            suggestion = SearchSuggestion.objects.get(pk=pk)
            current_order = suggestion.order

            # Find the suggestion with the next higher order
            next_suggestion = (
                SearchSuggestion.objects.filter(order__gt=current_order)
                .order_by("order")
                .first()
            )

            if next_suggestion:
                # Swap orders
                temp_order = -999999  # Temporary order to avoid conflicts
                suggestion.order = temp_order
                suggestion.save(update_fields=["order"])

                next_order = next_suggestion.order
                next_suggestion.order = current_order
                next_suggestion.save(update_fields=["order"])

                suggestion.order = next_order
                suggestion.save(update_fields=["order"])

                messages.success(request, "Suggestion moved down")
            else:
                messages.info(request, "Already at the bottom")

        except SearchSuggestion.DoesNotExist:
            messages.error(request, "Suggestion not found")
        except Exception as e:
            logger.error(f"Error moving suggestion down: {e}")
            messages.error(request, f"Error: {str(e)}")

    return redirect("admin:search_suggestion_manager")


@staff_member_required
def delete_search_suggestion(request, pk):
    """Delete a search suggestion"""
    if request.method == "POST":
        try:
            suggestion = SearchSuggestion.objects.get(pk=pk)
            entity_name = suggestion.get_entity_display_name()
            suggestion.delete()
            messages.success(request, f'Deleted suggestion for "{entity_name}"')
        except SearchSuggestion.DoesNotExist:
            messages.error(request, "Suggestion not found")
        except Exception as e:
            logger.error(f"Error deleting suggestion: {e}")
            messages.error(request, f"Error: {str(e)}")

    return redirect("admin:search_suggestion_manager")


@staff_member_required
def toggle_search_suggestion(request, pk):
    """Toggle active status of a search suggestion"""
    if request.method == "POST":
        try:
            suggestion = SearchSuggestion.objects.get(pk=pk)
            suggestion.is_active = not suggestion.is_active
            suggestion.save()
            status = "activated" if suggestion.is_active else "deactivated"
            messages.success(request, f"Successfully {status} suggestion")
        except SearchSuggestion.DoesNotExist:
            messages.error(request, "Suggestion not found")
        except Exception as e:
            logger.error(f"Error toggling suggestion: {e}")
            messages.error(request, f"Error: {str(e)}")

    return redirect("admin:search_suggestion_manager")
