import time
from datetime import datetime

from celery import shared_task
from loguru import logger
from opentelemetry import trace


@shared_task
def ping(message="Hello Celery!"):
    """
    Simple test task that just reports it was executed.
    Returns the message along with timestamp.
    """
    now = datetime.now().isoformat()
    logger.info(f"Running ping task with message: {message}")
    # Add small delay to simulate work
    time.sleep(1)
    result = f"PONG at {now}: {message}"
    logger.success(f"Ping task completed: {result}")
    return result


@shared_task
def test_tracing():
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("test-parent-span") as parent:
        parent.set_attribute("custom.attribute", "parent-value")

        # Do some work
        import time

        time.sleep(1)

        # Create a child span
        with tracer.start_as_current_span("test-child-span") as child:
            child.set_attribute("custom.attribute", "child-value")
            time.sleep(0.5)

    return "Tracing test completed"
