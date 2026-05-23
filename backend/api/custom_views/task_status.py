from celery.result import AsyncResult
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class TaskStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        result = AsyncResult(task_id)

        response_data = {
            "task_id": task_id,
            "status": result.status,
        }

        if result.ready():
            response_data["result"] = result.result

        return Response(response_data)
