import time

import requests
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from loguru import logger
from opentelemetry import trace
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

CustomUser = get_user_model()


@swagger_auto_schema(
    method="get",
    operation_description="Test basic OpenTelemetry tracing functionality",
    responses={
        200: openapi.Response(
            description="Tracing test successful",
            examples={
                "application/json": {
                    "status": "success",
                    "message": "Tracing test completed",
                    "users_count": 1,
                    "method": "GET",
                    "path": "/api/debug-tracing/test-tracing/",
                    "user_model": "CustomUser",
                }
            },
        )
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def test_tracing(request):
    """
    Test basic OpenTelemetry tracing functionality.

    WHAT IT DOES:
    - Creates a manual span called "debug-test-span"
    - Tests database query (CustomUser.objects.count()) - auto-traced by psycopg2 instrumentation
    - Tests external HTTP call to httpbin.org - auto-traced by requests instrumentation
    - Sets custom attributes on spans for debugging

    HOW TO CHECK IN JAEGER:
    1. Run: curl http://localhost:8000/api/debug-tracing/test-tracing/
    2. Go to http://localhost:16686
    3. Select service: "diavgeia-django"
    4. Look for operation: "GET /api/debug-tracing/test-tracing/"
    5. Click on the trace to see:
       - Main span with attributes: debug.test, debug.method, debug.path
       - Database query span (auto-generated) showing SQL execution time
       - HTTP request span (auto-generated) showing external API call
    """
    try:
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("debug-test-span") as span:
            span.set_attribute("debug.test", "hello")
            span.set_attribute("debug.method", request.method)
            span.set_attribute("debug.path", request.path)

            # Test database query with CustomUser - this creates auto-traced SQL spans
            user_count = CustomUser.objects.count()
            span.set_attribute("debug.user_count", user_count)

            # Test external HTTP call - this creates auto-traced HTTP spans
            try:
                response = requests.get("https://httpbin.org/delay/1", timeout=5)
                span.set_attribute("debug.external_call", response.status_code)
            except Exception as e:
                span.set_attribute("debug.external_error", str(e))

        return Response(
            {
                "status": "success",
                "message": "Tracing test completed",
                "users_count": user_count,
                "method": request.method,
                "path": request.path,
                "user_model": CustomUser.__name__,
            }
        )

    except Exception as e:
        logger.error(f"Tracing test failed: {e}")
        return Response({"status": "error", "error": str(e)}, status=500)


@swagger_auto_schema(
    method="get",
    operation_description="Check OpenTelemetry environment and connectivity",
    responses={
        200: openapi.Response(
            description="Environment check results",
            examples={
                "application/json": {
                    "environment": {"JAEGER_HOST": "jaeger", "JAEGER_PORT": "4317"},
                    "connectivity": {"jaeger:4317": "connected"},
                }
            },
        )
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def debug_environment(request):
    """
    Check OpenTelemetry environment variables and Jaeger connectivity.

    WHAT IT DOES:
    - Shows environment variables (JAEGER_HOST, JAEGER_PORT, etc.)
    - Tests network connectivity to Jaeger collector
    - Helps diagnose why traces might not be appearing

    HOW TO CHECK IN JAEGER:
    1. Run: curl http://localhost:8000/api/debug-tracing/environment/
    2. Check the response - if connectivity shows "connected", Jaeger is reachable
    3. If traces still don't appear, check:
       - Environment variables are set correctly
       - Jaeger container is running (docker ps | grep jaeger)
       - No firewall blocking port 4317
    """
    import os
    import socket

    env_vars = {
        "JAEGER_HOST": os.getenv("JAEGER_HOST", "not-set"),
        "JAEGER_PORT": os.getenv("JAEGER_PORT", "not-set"),
        "DJANGO_SETTINGS_MODULE": os.getenv("DJANGO_SETTINGS_MODULE", "not-set"),
        "OTEL_SERVICE_NAME": os.getenv("OTEL_SERVICE_NAME", "not-set"),
    }

    # Test network connectivity
    connectivity = {}
    jaeger_host = os.getenv("JAEGER_HOST", "jaeger")
    jaeger_port = int(os.getenv("JAEGER_PORT", "4317"))

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((jaeger_host, jaeger_port))
        sock.close()
        connectivity[f"{jaeger_host}:{jaeger_port}"] = (
            "connected" if result == 0 else f"failed-{result}"
        )
    except Exception as e:
        connectivity[f"{jaeger_host}:{jaeger_port}"] = f"error-{str(e)}"

    return Response(
        {
            "environment": env_vars,
            "connectivity": connectivity,
            "hostname": socket.gethostname(),
            "timestamp": time.time(),
        }
    )


@swagger_auto_schema(
    method="post",
    operation_description="Test Celery task tracing",
    responses={
        200: openapi.Response(
            description="Celery task triggered",
            examples={
                "application/json": {
                    "status": "task_triggered",
                    "task_id": "8d5cf89a-5d29-4a25-8630-89562594db9f",
                    "message": "Check Jaeger for celery traces in ~30 seconds",
                }
            },
        )
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def test_celery_tracing(request):
    """
    Test Celery task tracing by triggering a real registered task.

    WHAT IT DOES:
    - Triggers a properly registered Celery task with tracing
    - Task creates nested spans to show worker activity
    - Shows task execution, timing, and completion in traces

    HOW TO CHECK IN JAEGER:
    1. Run: curl -X POST http://localhost:8000/api/debug-tracing/test-celery/
    2. Wait 10-15 seconds for task to complete
    3. Go to http://localhost:16686
    4. Select service: "diavgeia-celery" (not diavgeia-django!)
    5. Look for operation: "celery-test-task"
    6. You should see:
       - Task execution span with duration ~3 seconds
       - Nested spans: task-initialization, task-main-work, task-cleanup
       - Custom attributes: task.name, task.delay, task.id, task.status
       - Any errors if task failed
    """
    try:
        # Import the properly registered task
        from api.tasks import test_tracing_task

        # Get delay from request (default 3 seconds)
        delay_seconds = (
            int(request.data.get("delay", 3)) if hasattr(request, "data") else 3
        )

        # Trigger the task
        task = test_tracing_task.delay(delay_seconds)

        return Response(
            {
                "status": "task_triggered",
                "task_id": task.id,
                "task_name": "test_tracing_task",
                "delay_seconds": delay_seconds,
                "message": f"Check Jaeger for celery traces in ~{delay_seconds + 5} seconds",
            }
        )

    except Exception as e:
        return Response(
            {
                "status": "error",
                "error": str(e),
                "details": "Make sure the Celery worker is running and can import api.tasks",
            },
            status=500,
        )


@csrf_exempt
def test_error_tracing(request):
    """
    Test error tracing by simulating and handling exceptions.

    WHAT IT DOES:
    - Creates a span and simulates a ZeroDivisionError
    - Records the exception in the span
    - Sets span status to ERROR
    - Shows proper error handling in traces

    HOW TO CHECK IN JAEGER:
    1. Run: curl http://localhost:8000/api/debug-tracing/test-error/
    2. Go to http://localhost:16686
    3. Select service: "diavgeia-django"
    4. Look for operation: "error-test-span"
    5. Click on the trace to see:
       - Red/error indicator on the span
       - Exception details in the span
       - Custom attributes: test.error_type, error.handled
    """
    try:
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("error-test-span") as span:
            span.set_attribute("test.error_type", "simulated")

            # Simulate an error
            try:
                1 / 0
            except ZeroDivisionError as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR)
                span.set_attribute("error.handled", True)

        return JsonResponse(
            {"status": "error_simulated", "message": "Check Jaeger for error traces"}
        )

    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=500)


@csrf_exempt
def test_nested_tracing(request):
    """
    Test nested spans to show parent-child relationships in traces.

    WHAT IT DOES:
    - Creates a parent span "parent-operation"
    - Creates nested spans: "database-operations" and "processing"
    - Shows how spans relate to each other hierarchically
    - Demonstrates timing breakdown across operations

    HOW TO CHECK IN JAEGER:
    1. Run: curl http://localhost:8000/api/debug-tracing/test-nested/
    2. Go to http://localhost:16686
    3. Select service: "diavgeia-django"
    4. Look for operation: "parent-operation"
    5. Click on the trace to see:
       - Parent span with total duration
       - Child spans indented under parent
       - Timing for each nested operation
       - Custom attributes on each span level
    """
    try:
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("parent-operation") as parent_span:
            parent_span.set_attribute("operation.type", "nested_test")

            # Simulate some work
            time.sleep(0.5)

            # Nested span for database operations with CustomUser
            with tracer.start_as_current_span("database-operations") as db_span:
                users = list(CustomUser.objects.all()[:5])
                db_span.set_attribute("users.queried", len(users))

                # Also get some user-specific attributes if they exist
                if users:
                    first_user = users[0]
                    db_span.set_attribute("first_user.id", str(first_user.id))
                    if hasattr(first_user, "email"):
                        db_span.set_attribute("first_user.email", first_user.email)

            # Another nested span
            with tracer.start_as_current_span("processing") as proc_span:
                processed_data = []
                for user in users:
                    user_data = {"id": user.id}
                    if hasattr(user, "username"):
                        user_data["username"] = user.username
                    if hasattr(user, "email"):
                        user_data["email"] = user.email
                    processed_data.append(user_data)

                proc_span.set_attribute("data.processed", len(processed_data))

        return JsonResponse(
            {
                "status": "nested_test_complete",
                "users_processed": len(processed_data),
                "user_model": CustomUser.__name__,
                "message": "Check Jaeger for nested span structure",
            }
        )

    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=500)


@csrf_exempt
def test_user_operations(request):
    """
    Test operations with CustomUser model to verify database tracing.

    WHAT IT DOES:
    - Tests user creation and querying operations
    - Shows database query patterns in traces
    - Demonstrates how ORM operations appear in traces

    HOW TO CHECK IN JAEGER:
    1. Run: curl http://localhost:8000/api/debug-tracing/test-user-operations/
    2. Go to http://localhost:16686
    3. Select service: "diavgeia-django"
    4. Look for operation: "user-operations-test"
    5. Click on the trace to see:
       - Database query spans (auto-generated by psycopg2 instrumentation)
       - SQL execution times
       - Query patterns (SELECT, INSERT, etc.)
       - Custom attributes about user operations
    """
    try:
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("user-operations-test") as span:
            span.set_attribute("operation.type", "user_crud_test")

            # Test creating a user (if you have the right fields)
            with tracer.start_as_current_span("create_user") as create_span:
                # This assumes your CustomUser has these fields - adjust as needed
                test_user_data = {
                    "username": "test_tracing_user",
                    "email": "test@tracing.local",
                }

                # Check what fields your CustomUser actually has
                user_fields = [f.name for f in CustomUser._meta.get_fields()]
                create_span.set_attribute("user.fields", str(user_fields))

                # Only create if we can (you might need to handle this differently)
                try:
                    # This is just an example - adjust based on your CustomUser model
                    test_user, created = CustomUser.objects.get_or_create(
                        username=test_user_data["username"], defaults=test_user_data
                    )
                    create_span.set_attribute("user.created", created)
                    create_span.set_attribute("user.id", str(test_user.id))
                except Exception as e:
                    create_span.set_attribute("user.create_error", str(e))
                    # Just query existing users instead
                    test_user = CustomUser.objects.first()
                    create_span.set_attribute("user.used_existing", True)

            # Test querying users
            with tracer.start_as_current_span("query_users") as query_span:
                user_count = CustomUser.objects.count()
                recent_users = list(CustomUser.objects.order_by("-id")[:3])
                query_span.set_attribute("users.total_count", user_count)
                query_span.set_attribute("users.recent_count", len(recent_users))

        return JsonResponse(
            {
                "status": "user_operations_complete",
                "user_model": CustomUser.__name__,
                "user_count": user_count,
                "recent_users": len(recent_users),
                "fields": user_fields,
            }
        )

    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=500)


# Add this enhanced version to see more spans
@api_view(["GET"])
@permission_classes([AllowAny])
def test_tracing_verbose(request):
    """Enhanced tracing test with more visible operations"""
    try:
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("verbose-test-main") as main_span:
            main_span.set_attribute("test.type", "verbose")
            main_span.set_attribute("request.method", request.method)

            # Force multiple database operations
            with tracer.start_as_current_span("database-operations") as db_span:
                # Multiple queries to make DB activity more visible
                user_count = CustomUser.objects.count()
                list(CustomUser.objects.all()[:3])  # DB activity for tracing

                # Create a user to generate INSERT
                from django.utils import timezone

                test_username = f"trace_test_{int(timezone.now().timestamp())}"

                try:
                    new_user = CustomUser.objects.create(
                        username=test_username, email=f"{test_username}@example.com"
                    )
                    db_span.set_attribute("user.created_id", new_user.id)
                except:
                    db_span.set_attribute("user.creation", "failed")

                db_span.set_attribute("users.total", user_count)
                db_span.set_attribute("queries.executed", 3)

            # Force HTTP operations
            with tracer.start_as_current_span("external-calls") as http_span:
                try:
                    # Multiple HTTP calls
                    response1 = requests.get("https://httpbin.org/uuid", timeout=3)
                    response2 = requests.get("https://httpbin.org/ip", timeout=3)

                    http_span.set_attribute("http.calls", 2)
                    http_span.set_attribute("http.status1", response1.status_code)
                    http_span.set_attribute("http.status2", response2.status_code)
                except Exception as e:
                    http_span.set_attribute("http.error", str(e))

            # Simulate processing time
            with tracer.start_as_current_span("processing") as proc_span:
                time.sleep(0.1)  # Make it visible
                proc_span.set_attribute("processing.duration_ms", 100)

        return Response(
            {
                "status": "verbose_test_complete",
                "message": "Check Jaeger for detailed trace breakdown",
            }
        )

    except Exception as e:
        return Response({"status": "error", "error": str(e)}, status=500)


@swagger_auto_schema(
    method="get",
    operation_description="Force trace export to verify Jaeger connectivity",
)
@api_view(["GET"])
@permission_classes([AllowAny])
def force_trace_export(request):
    """
    Force a trace export to verify Jaeger connectivity.

    WHAT IT DOES:
    - Creates multiple spans with explicit attributes
    - Forces immediate export (bypasses batching)
    - Tests if traces reach Jaeger

    HOW TO CHECK:
    1. Run: curl http://localhost:8000/api/debug-tracing/force-export/
    2. Check Jaeger immediately (no delay)
    3. Should see "force-export-test" operation
    """
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer(__name__)

        # Create a span with rich data
        with tracer.start_as_current_span("force-export-test") as span:
            span.set_attribute("test.type", "forced_export")
            span.set_attribute("test.timestamp", int(time.time()))
            span.set_attribute("test.service", "diavgeia-django")
            span.set_attribute("request.method", request.method)
            span.set_attribute("request.path", request.path)

            # Add some nested spans
            with tracer.start_as_current_span("nested-operation-1") as nested1:
                nested1.set_attribute("operation.id", 1)
                time.sleep(0.1)

                with tracer.start_as_current_span("nested-operation-2") as nested2:
                    nested2.set_attribute("operation.id", 2)
                    time.sleep(0.1)

            # Add event
            span.add_event("test.event", {"message": "Force export test completed"})

        # Force immediate export by getting the provider and flushing
        provider = trace.get_tracer_provider()
        if hasattr(provider, "_active_span_processor"):
            provider._active_span_processor.force_flush(timeout_millis=5000)

        return Response(
            {
                "status": "force_export_complete",
                "message": "Check Jaeger immediately - traces should appear without delay",
                "service_name": "diavgeia-django",
                "timestamp": int(time.time()),
            }
        )

    except Exception as e:
        logger.error(f"Force export failed: {e}")
        return Response({"status": "error", "error": str(e)}, status=500)


@swagger_auto_schema(
    method="post",
    operation_description="Test simple Celery task",
    responses={
        200: openapi.Response(
            description="Simple Celery task triggered",
            examples={
                "application/json": {
                    "status": "task_triggered",
                    "task_id": "simple-task-id",
                    "message": "Simple task triggered successfully",
                }
            },
        )
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def test_simple_task(request):
    """
    Test simple Celery task to verify basic worker functionality.

    WHAT IT DOES:
    - Triggers a simple registered Celery task
    - Task runs for 1 second with basic tracing
    - Good for testing basic Celery connectivity

    HOW TO CHECK IN JAEGER:
    1. Run: curl -X POST http://localhost:8000/api/debug-tracing/test-simple-task/
    2. Wait 5 seconds for task to complete
    3. Go to http://localhost:16686
    4. Select service: "diavgeia-celery"
    5. Look for operation: "simple-celery-task"
    """
    try:
        from api.tasks import test_simple_task

        message = (
            request.data.get("message", "Hello from Django!")
            if hasattr(request, "data")
            else "Hello from Django!"
        )

        # Trigger the simple task
        task = test_simple_task.delay(message)

        return Response(
            {
                "status": "task_triggered",
                "task_id": task.id,
                "task_name": "test_simple_task",
                "message": "Simple task triggered successfully",
            }
        )

    except Exception as e:
        return Response({"status": "error", "error": str(e)}, status=500)
