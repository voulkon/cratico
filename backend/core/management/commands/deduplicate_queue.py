"""
Management command to deduplicate RabbitMQ queue messages.

This command:
1. Connects to RabbitMQ
2. Fetches all messages from the celery queue
3. Extracts unique entity ID combinations
4. Re-publishes only the unique combinations back to the queue
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

import kombu
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Deduplicate messages in the RabbitMQ celery queue by entity IDs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually modifying the queue",
        )
        parser.add_argument(
            "--queue",
            type=str,
            default="celery",
            help="Name of the queue to deduplicate (default: celery)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        queue_name = options["queue"]

        self.stdout.write(
            self.style.WARNING(f"Starting queue deduplication for '{queue_name}'...")
        )
        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Connect to RabbitMQ
        broker_url = settings.CELERY_BROKER_URL
        self.stdout.write(f"Connecting to broker: {broker_url}")

        with kombu.Connection(broker_url) as conn:
            # Create a queue object
            queue = conn.SimpleQueue(queue_name)

            # Fetch all messages
            messages = []
            self.stdout.write("Fetching messages from queue...")

            try:
                while True:
                    message = queue.get(block=False, timeout=1)
                    messages.append(message)
                    if len(messages) % 100 == 0:
                        self.stdout.write(f"Fetched {len(messages)} messages...")
            except queue.Empty:
                pass

            self.stdout.write(
                self.style.SUCCESS(f"Fetched {len(messages)} total messages")
            )

            # Parse messages and extract entity IDs
            task_data = []
            unique_combinations: Dict[Tuple, List[dict]] = defaultdict(list)

            for msg in messages:
                try:
                    # Decode message body
                    body = msg.payload
                    headers = msg.headers

                    # Extract the entity IDs from the args
                    # Body format: [[["entity_id1", "entity_id2"]], {...}, {...}]
                    if isinstance(body, list) and len(body) >= 1:
                        args = body[0]
                        if isinstance(args, list) and len(args) >= 1:
                            entity_ids = args[0]
                            if isinstance(entity_ids, list):
                                # Create a tuple key for uniqueness check
                                # Sort to ensure ['A', 'B'] and ['B', 'A'] are considered the same
                                key = tuple(sorted(entity_ids))

                                task_info = {
                                    "entity_ids": entity_ids,
                                    "key": key,
                                    "task": headers.get("task", "unknown"),
                                    "parent_ada": (
                                        body[1].get("parent_ada", "unknown")
                                        if len(body) > 1
                                        else "unknown"
                                    ),
                                    "message": msg,
                                    "body": body,
                                    "headers": headers,
                                }

                                unique_combinations[key].append(task_info)
                                task_data.append(task_info)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error parsing message: {e}"))
                    continue

            # Report statistics
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.SUCCESS(f"Total messages: {len(messages)}"))
            self.stdout.write(
                self.style.SUCCESS(f"Successfully parsed: {len(task_data)}")
            )
            self.stdout.write(
                self.style.SUCCESS(f"Unique combinations: {len(unique_combinations)}")
            )
            self.stdout.write(
                self.style.WARNING(
                    f"Duplicates to remove: {len(task_data) - len(unique_combinations)}"
                )
            )
            self.stdout.write("=" * 80 + "\n")

            # Show duplicate statistics
            duplicates = {k: v for k, v in unique_combinations.items() if len(v) > 1}
            if duplicates:
                self.stdout.write(
                    self.style.WARNING(
                        f"\nFound {len(duplicates)} entity combinations with duplicates:"
                    )
                )
                for key, tasks in sorted(
                    duplicates.items(), key=lambda x: len(x[1]), reverse=True
                )[:10]:
                    self.stdout.write(f"  {list(key)}: {len(tasks)} occurrences")
                if len(duplicates) > 10:
                    self.stdout.write(f"  ... and {len(duplicates) - 10} more")

            if not dry_run:
                # Acknowledge all original messages (remove them)
                self.stdout.write("\nAcknowledging all original messages...")
                for msg in messages:
                    msg.ack()
                self.stdout.write(
                    self.style.SUCCESS(
                        "All messages acknowledged and removed from queue"
                    )
                )

                # Re-publish unique messages
                self.stdout.write("\nRe-publishing unique messages...")
                with conn.default_channel as channel:
                    producer = kombu.Producer(channel)

                    count = 0
                    for key, tasks in unique_combinations.items():
                        # Take the first occurrence of each unique combination
                        task = tasks[0]

                        # Serialize the body to JSON bytes
                        body_bytes = json.dumps(task["body"]).encode("utf-8")

                        # Re-publish the message
                        producer.publish(
                            body_bytes,
                            routing_key=queue_name,
                            exchange="",
                            headers=task["headers"],
                            content_type="application/json",
                            content_encoding="utf-8",
                        )
                        count += 1
                        if count % 100 == 0:
                            self.stdout.write(
                                f"Re-published {count}/{len(unique_combinations)} messages..."
                            )

                    self.stdout.write(
                        self.style.SUCCESS(f"\nRe-published {count} unique messages")
                    )
            else:
                self.stdout.write("\nDRY RUN - Would have:")
                self.stdout.write(
                    f"  1. Acknowledged and removed {len(messages)} messages"
                )
                self.stdout.write(
                    f"  2. Re-published {len(unique_combinations)} unique messages"
                )
                self.stdout.write(
                    f"  3. Eliminated {len(task_data) - len(unique_combinations)} duplicate messages"
                )

                # Don't acknowledge messages in dry run
                for msg in messages:
                    msg.requeue()

            queue.close()

        self.stdout.write("\n" + "=" * 80)
        if dry_run:
            self.stdout.write(self.style.SUCCESS("DRY RUN COMPLETE - No changes made"))
        else:
            self.stdout.write(self.style.SUCCESS("DEDUPLICATION COMPLETE"))
        self.stdout.write("=" * 80)
