"""Example showing how shared rate limiting works across multiple client instances."""

from gemi.src.client import GemiDataClient


def demonstrate_shared_rate_limiting():
    """Show how multiple client instances share rate limiting state."""

    # Create multiple client instances with the SAME API key
    client1 = GemiDataClient(api_key="same-key")
    client2 = GemiDataClient(api_key="same-key")
    client3 = GemiDataClient(api_key="same-key")

    print("=== Demonstrating Shared Rate Limiting ===")

    # Check initial rate limit status
    status = client1._base_client.get_rate_limit_status()
    print(f"Initial status: {status}")

    try:
        # Make requests from different client instances
        print("\nMaking requests from different client instances...")

        # Client 1 makes some requests
        print("Client 1: Getting prefectures...")
        prefectures = client1.reference.get_prefectures()
        print(f"Got {len(prefectures)} prefectures")

        # Check status after client1's request
        status = client2._base_client.get_rate_limit_status()
        print(f"Status after client1 request: {status}")

        # Client 2 makes a request - should see the rate limit state from client1
        print("\nClient 2: Getting local offices...")
        offices = client2.reference.get_local_offices()
        print(f"Got {len(offices)} local offices")

        # Client 3 checks status - should see requests from both client1 and client2
        status = client3._base_client.get_rate_limit_status()
        print(f"Status after client1 and client2 requests: {status}")

        # Simulate hitting rate limit
        print("\nSimulating multiple rapid requests to trigger rate limiting...")
        for i in range(10):
            try:
                (
                    client1.reference.get_prefectures()
                    if i % 2 == 0
                    else client2.reference.get_local_offices()
                )
                print(f"Request {i+1}: Success")
            except Exception as e:
                print(f"Request {i+1}: Failed - {e}")
                break

        # Check final status
        status = client3._base_client.get_rate_limit_status()
        print(f"\nFinal status: {status}")

        if status["backoff_time"]:
            print(
                f"All clients will now back off for {status['backoff_time']:.1f} seconds"
            )

    except Exception as e:
        print(f"Error during demonstration: {e}")


def demonstrate_different_api_keys():
    """Show that different API keys have separate rate limiting."""

    print("\n=== Demonstrating Separate Rate Limiting for Different API Keys ===")

    # Create clients with different API keys
    client_key1 = GemiDataClient(api_key="key-1")
    client_key2 = GemiDataClient(api_key="key-2")

    # Each should have separate rate limiting
    status1 = client_key1._base_client.get_rate_limit_status()
    status2 = client_key2._base_client.get_rate_limit_status()

    print(f"Client with key-1 status: {status1}")
    print(f"Client with key-2 status: {status2}")

    print("Different API keys maintain separate rate limiting state!")


def demonstrate_registry_pattern():
    """Show how to use the client registry for even better management."""
    from gemi.src.client_registry import GemiClientRegistry
    from gemi.src.config import GemiConfig

    print("\n=== Demonstrating Client Registry Pattern ===")

    # Set up different client configurations
    default_config = GemiConfig(api_key="main-key", timeout=30)
    batch_config = GemiConfig(api_key="main-key", timeout=120, max_retries=5)

    # Register clients
    GemiClientRegistry.get_client("default", default_config)
    GemiClientRegistry.get_client("batch", batch_config)

    # Different parts of your application can get the same client instances
    class ServiceA:
        def __init__(self):
            self.client = GemiClientRegistry.get_default_client()

        def do_work(self):
            return self.client.reference.get_prefectures()

    class ServiceB:
        def __init__(self):
            self.client = (
                GemiClientRegistry.get_default_client()
            )  # Same instance as ServiceA

        def do_work(self):
            return self.client.reference.get_local_offices()

    class BatchService:
        def __init__(self):
            self.client = GemiClientRegistry.get_client(
                "batch"
            )  # Different config, same rate limiting

        def process_batch(self):
            return "Batch processing with high timeout client"

    # Create services
    service_a = ServiceA()
    service_b = ServiceB()
    batch_service = BatchService()

    print("ServiceA and ServiceB share the same client instance and rate limiting")
    print(
        "BatchService uses a different configuration but shares rate limiting for the same API key"
    )

    # Verify they share the same client instance
    print(
        f"ServiceA and ServiceB use same client: {service_a.client is service_b.client}"
    )
    print(
        f"Batch service uses different client: {batch_service.client is service_a.client}"
    )


if __name__ == "__main__":
    # Note: These examples will fail without a real API key
    # They're meant to show the structure and behavior

    print("This example shows the structure of shared rate limiting.")
    print("To run with real API calls, set GEMI_API_KEY environment variable.")

    # You can still run the registry demonstration
    demonstrate_registry_pattern()
