from core.tasks import ping
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test that Celery task pipeline is working"

    def add_arguments(self, parser):
        parser.add_argument(
            "--message",
            type=str,
            default="Hello from management command!",
            help="Message to send to the ping task",
        )
        parser.add_argument(
            "--wait",
            action="store_true",
            help="Wait for task result instead of just queueing it",
        )

    def handle(self, *args, **options):
        message = options["message"]
        self.stdout.write(f"Sending ping task with message: {message}")

        # Queue the task
        task = ping.delay(message)
        self.stdout.write(self.style.SUCCESS(f"Task queued with ID: {task.id}"))

        # Optionally wait for result
        if options["wait"]:
            self.stdout.write("Waiting for task result...")
            try:
                result = task.get(timeout=10)  # Wait up to 10 sec
                self.stdout.write(
                    self.style.SUCCESS(f"Task completed! Result: {result}")
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error getting task result: {e}"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Task queued in background. Check Flower UI at http://localhost:5555 to see results."
                )
            )
