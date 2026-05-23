import time

from celery import shared_task
from opentelemetry import trace


@shared_task(bind=True)
def test_tracing_task(self, delay_seconds=2):
    """
    Test Celery task for OpenTelemetry tracing.

    This task will create spans to test Celery worker tracing.
    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("celery-test-task") as span:
        span.set_attribute("task.name", "test_tracing_task")
        span.set_attribute("task.delay", delay_seconds)
        span.set_attribute("task.id", self.request.id)
        span.set_attribute("task.retries", self.request.retries)

        # Simulate some work with nested spans
        with tracer.start_as_current_span("task-initialization") as init_span:
            init_span.set_attribute("step", "initialization")
            time.sleep(0.5)

        with tracer.start_as_current_span("task-main-work") as work_span:
            work_span.set_attribute("step", "main_work")
            work_span.set_attribute("work.duration", delay_seconds)
            time.sleep(delay_seconds)

        with tracer.start_as_current_span("task-cleanup") as cleanup_span:
            cleanup_span.set_attribute("step", "cleanup")
            time.sleep(0.2)

        span.set_attribute("task.status", "completed")

        return {
            "status": "completed",
            "delay": delay_seconds,
            "task_id": self.request.id,
            "message": "Tracing test task completed successfully",
        }


@shared_task(bind=True)
def test_error_task(self, should_fail=True):
    """
    Test task that demonstrates error tracing.
    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("celery-error-test-task") as span:
        span.set_attribute("task.name", "test_error_task")
        span.set_attribute("task.should_fail", should_fail)
        span.set_attribute("task.id", self.request.id)

        if should_fail:
            # Record the exception in the span
            try:
                1 / 0  # Intentional ZeroDivisionError for tracing
            except ZeroDivisionError as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR)
                span.set_attribute("error.type", "ZeroDivisionError")
                span.set_attribute("error.handled", True)

                # Re-raise so Celery marks the task as failed
                raise
        else:
            span.set_attribute("task.status", "completed")
            return {"status": "success", "message": "Task completed without errors"}


@shared_task
def test_simple_task(message="Hello from Celery!"):
    """
    Simple task for basic Celery testing.
    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("simple-celery-task") as span:
        span.set_attribute("task.name", "test_simple_task")
        span.set_attribute("task.message", message)

        # Just a quick task
        time.sleep(1)

        return {"message": message, "status": "completed"}
