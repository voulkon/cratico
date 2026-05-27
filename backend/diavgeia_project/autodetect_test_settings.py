"""
Auto-detect which test settings to use based on environment
This file must be specified as the DJANGO_SETTINGS_MODULE in pytest.ini
"""

import os

# Check if PostgreSQL tests are enabled via environment variable
if os.environ.get("PG_TEST"):
    print("PostgreSQL tests enabled - using PostgreSQL database")
    from diavgeia_project.pg_test_settings import *
else:
    print("Standard tests - using SQLite in-memory database")
    from diavgeia_project.settings import *
    from diavgeia_project.test_settings import *
