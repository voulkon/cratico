import os
import pickle
from datetime import datetime

from celery import current_app
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Monitor and manage distributed decision import tasks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--status",
            action="store_true",
            help="Show status of all distributed tasks",
        )
        parser.add_argument(
            "--pickles",
            action="store_true",
            help="List all pickle files and their status",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Retry all failed pickle files",
        )
        parser.add_argument(
            "--cleanup",
            action="store_true",
            help="Clean up old completed pickle files",
        )

    def handle(self, *args, **options):
        if options["status"]:
            self._show_task_status()

        if options["pickles"]:
            self._show_pickle_status()

        if options["retry_failed"]:
            self._retry_failed_pickles()

        if options["cleanup"]:
            self._cleanup_old_files()

    def _show_task_status(self):
        """Show status of active Celery tasks"""
        self.stdout.write(self.style.SUCCESS("=== Celery Task Status ==="))

        try:
            # Get active tasks
            inspect = current_app.control.inspect()
            active_tasks = inspect.active()
            scheduled_tasks = inspect.scheduled()

            if active_tasks:
                self.stdout.write("Active Tasks:")
                for worker, tasks in active_tasks.items():
                    self.stdout.write(f"  Worker: {worker}")
                    for task in tasks:
                        task_name = task["name"].split(".")[-1]  # Get short name
                        self.stdout.write(f"    {task_name}: {task['id']}")
            else:
                self.stdout.write("No active tasks")

            if scheduled_tasks:
                self.stdout.write("Scheduled Tasks:")
                for worker, tasks in scheduled_tasks.items():
                    self.stdout.write(f"  Worker: {worker} - {len(tasks)} tasks")

        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Could not connect to Celery: {e}"))

    def _show_pickle_status(self):
        """Show status of all pickle files"""
        self.stdout.write(self.style.SUCCESS("=== Pickle Files Status ==="))

        pickle_base = "/code/logs/pickles"

        # Check pending pickles
        pending_dir = pickle_base
        pending_files = (
            [f for f in os.listdir(pending_dir) if f.endswith(".pkl")]
            if os.path.exists(pending_dir)
            else []
        )

        # Check completed pickles
        completed_dir = f"{pickle_base}/completed"
        completed_files = (
            [f for f in os.listdir(completed_dir) if f.endswith(".pkl")]
            if os.path.exists(completed_dir)
            else []
        )

        # Check failed pickles
        failed_dir = f"{pickle_base}/failed"
        failed_files = (
            [f for f in os.listdir(failed_dir) if f.endswith(".pkl")]
            if os.path.exists(failed_dir)
            else []
        )

        self.stdout.write(f"Pending: {len(pending_files)} files")
        self.stdout.write(f"Completed: {len(completed_files)} files")
        self.stdout.write(f"Failed: {len(failed_files)} files")

        # Show details of pending files
        if pending_files:
            self.stdout.write("\nPending Files:")
            for file in pending_files[:10]:  # Show first 10
                file_path = os.path.join(pending_dir, file)
                try:
                    with open(file_path, "rb") as f:
                        data = pickle.load(
                            f
                        )  # nosec: B301 - Internal pickle files for import queue
                    count = data.get("count", "unknown")
                    chunk_id = data.get("chunk_id", "unknown")
                    self.stdout.write(f"  {file}: {count} decisions, chunk {chunk_id}")
                except:
                    self.stdout.write(f"  {file}: (could not read)")

            if len(pending_files) > 10:
                self.stdout.write(f"  ... and {len(pending_files) - 10} more")

        # Show failed files details
        if failed_files:
            self.stdout.write("\nFailed Files:")
            for file in failed_files:
                self.stdout.write(f"  {file}")

    def _retry_failed_pickles(self):
        """Retry all failed pickle files"""
        failed_dir = "/code/logs/pickles/failed"

        if not os.path.exists(failed_dir):
            self.stdout.write("No failed pickles directory found")
            return

        failed_files = [f for f in os.listdir(failed_dir) if f.endswith(".pkl")]

        if not failed_files:
            self.stdout.write("No failed pickle files to retry")
            return

        self.stdout.write(f"Retrying {len(failed_files)} failed pickle files...")

        from core.tasks.tasks_decisions_import import store_decisions_from_pickle

        retried_count = 0
        for file in failed_files:
            file_path = os.path.join(failed_dir, file)

            try:
                # Move back to pending and retry
                pending_path = f"/code/logs/pickles/{file}"
                os.rename(file_path, pending_path)

                # Dispatch storage task with smaller batch size
                task = store_decisions_from_pickle.delay(pending_path, batch_size=10)

                self.stdout.write(f"  Retried {file} -> task {task.id}")
                retried_count += 1

            except Exception as e:
                self.stdout.write(f"  Failed to retry {file}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Retried {retried_count} pickle files"))

    def _cleanup_old_files(self):
        """Clean up old completed pickle files"""
        completed_dir = "/code/logs/pickles/completed"

        if not os.path.exists(completed_dir):
            self.stdout.write("No completed pickles directory found")
            return

        completed_files = [f for f in os.listdir(completed_dir) if f.endswith(".pkl")]

        if not completed_files:
            self.stdout.write("No completed pickle files to clean up")
            return

        # Only keep files from last 7 days
        cutoff_time = datetime.now().timestamp() - (7 * 24 * 60 * 60)

        cleaned_count = 0
        for file in completed_files:
            file_path = os.path.join(completed_dir, file)

            try:
                file_time = os.path.getmtime(file_path)
                if file_time < cutoff_time:
                    os.remove(file_path)
                    cleaned_count += 1
            except Exception as e:
                self.stdout.write(f"  Could not clean {file}: {e}")

        self.stdout.write(
            self.style.SUCCESS(f"Cleaned up {cleaned_count} old pickle files")
        )
