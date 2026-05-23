import json

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from users.models import CustomUser


class SecurityTracer:
    """Centralized utility for security event tracing"""

    def __init__(self):
        self.tracer = trace.get_tracer("diavgeia.security")

    def log_security_event(
        self,
        event_type,
        details=None,
        user=None,
        ip=None,
        clerk_id=None,
        severity="INFO",
    ):
        """
        Log a security event as an OpenTelemetry span

        Parameters:
            event_type: String describing event type (e.g. "authentication.clerk.success")
            details: Additional event details (string or dict)
            user: CustomUser object
            ip: Client IP address
            clerk_id: Clerk user ID (if available but user object isn't)
            severity: "INFO", "WARNING", "ERROR", or "CRITICAL"
        """
        # Create attributes for the security event
        attributes = {"security.event_type": event_type, "security.severity": severity}

        # Add user information if provided
        if user:
            if isinstance(user, CustomUser):
                attributes["security.user.id"] = str(user.id)
                attributes["security.user.username"] = user.username
                attributes["security.user.email"] = user.email if user.email else ""
                attributes["security.user.clerk_id"] = user.clerk_id or ""
                attributes["security.user.subscription"] = (
                    user.subscription.name if user.subscription else "none"
                )

        # If we have clerk_id but no user object
        elif clerk_id:
            attributes["security.clerk.id"] = clerk_id

        # Add IP address if provided
        if ip:
            attributes["security.client.ip"] = ip

        # Add details if provided
        if details:
            if isinstance(details, dict):
                # For structured data, add as individual attributes
                for key, value in details.items():
                    safe_key = key.replace(".", "_")
                    if isinstance(value, (str, int, float, bool)):
                        attributes[f"security.details.{safe_key}"] = value
                    else:
                        try:
                            attributes[f"security.details.{safe_key}"] = json.dumps(
                                value
                            )
                        except:
                            attributes[f"security.details.{safe_key}"] = str(value)
            else:
                # For simple details, just add as string
                attributes["security.details"] = str(details)

        # Create a span for this security event
        with self.tracer.start_as_current_span(
            f"security.{event_type}", attributes=attributes
        ) as span:
            # Set span status based on severity
            if severity in ["ERROR", "CRITICAL"]:
                span.set_status(StatusCode.ERROR)

            # Add security alert for critical events
            if severity == "CRITICAL":
                span.add_event(
                    "security.alert", {"level": "critical", "requires_attention": True}
                )


# Create a singleton instance for import
security_tracer = SecurityTracer()


# Helper function to get client IP, considering proxies
def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip
