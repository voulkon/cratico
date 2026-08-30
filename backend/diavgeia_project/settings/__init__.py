"""
Django settings for diavgeia_project project.

This module imports and combines all settings from individual modules.
For more information, see https://docs.djangoproject.com/en/5.0/ref/settings/
"""

import os
from pathlib import Path
from urllib.parse import urlparse

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Import application settings
from .apps import *

# Import authentication settings
from .auth import *

# Import base settings (SECRET_KEY, DEBUG, ALLOWED_HOSTS, etc.)
from .base import *

# Import cache configuration
from .cache import *

# Import Celery settings
from .celery import *

# Import database configuration
from .database import *
from .email import *

# Import external services settings (OpenSearch, GEMI, AWS, etc.)
from .external_services import *

# Import internationalization settings
from .internationalization import *

# Import logging configuration
from .logging import *

# Import middleware configuration
from .middleware import *

# Import orchestrator settings
from .orchestrator import *

# Import REST Framework settings
from .rest_framework import *

# Import security settings (CORS, CSP, cookies, etc.)
from .security import *

# Import static files settings
from .static import *

# Import templates configuration
from .templates import *

from .ai import *