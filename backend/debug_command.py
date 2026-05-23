#!/usr/bin/env python
import os
import sys

import debugpy

# Print information about the environment
# print(f"Current directory: {os.getcwd()}")
# print(f"sys.path: {sys.path}")

# Set the Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "diavgeia_project.settings")

# Configure debugpy
debugpy.listen(
    ("0.0.0.0", 8003)
)  # nosec: B104 - Debug server for local development only
print("...Waiting for debugger to attach...")
debugpy.wait_for_client()
print("[SCAN] Debugger attached! Starting command...")

# Run the management command
if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    # Fix: Adjust the command line arguments
    # Replace the script name with 'manage.py' to mimic normal Django commands
    adjusted_args = ["manage.py"] + sys.argv[1:]
    print(f"Executing with args: {adjusted_args}")

    execute_from_command_line(adjusted_args)
