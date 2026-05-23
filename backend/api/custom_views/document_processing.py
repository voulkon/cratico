from core.tasks import process_documents_task
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ProcessDocumentsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check subscription permissions
        if (
            not request.user.subscription
            or not request.user.subscription.can_queue_bulk_tasks
        ):
            return Response(
                {"error": "Your subscription doesn't allow bulk processing"}, status=403
            )

        # Get parameters from request
        ada_list = request.data.get("ada_list", [])
        from_date = request.data.get("from_date")
        limit = int(request.data.get("limit", 50))

        # Queue the task
        task = process_documents_task.delay(
            ada_list=ada_list, from_date=from_date, limit=limit, user_id=request.user.id
        )

        return Response({"task_id": task.id, "status": "Processing queued"})
