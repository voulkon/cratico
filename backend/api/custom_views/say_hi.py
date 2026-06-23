from core.tasks import say_hi as say_hi_task
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class SayHiView(APIView):

    def post(self, request):
        message = request.data.get("message", "Hi from the worker!")
        task = say_hi_task.delay(message=message)
        return Response({"task_id": task.id, "status": "Worker will say hi"})
