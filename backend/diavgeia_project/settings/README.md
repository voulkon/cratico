# Django Settings Structure

This directory contains a modular Django settings configuration. The settings are split into logical modules for better maintainability and organization.

## Structure

- `__init__.py` - Main entry point that imports all settings modules
- `base.py` - Core settings (SECRET_KEY, DEBUG, ALLOWED_HOSTS, BASE_DIR, etc.)
- `apps.py` - INSTALLED_APPS configuration
- `database.py` - Database configuration (PostgreSQL)
- `cache.py` - Cache configuration (Redis)
- `security.py` - Security settings (CORS, CSP, cookies)
- `rest_framework.py` - REST Framework configuration
- `celery.py` - Celery configuration
- `logging.py` - Logging configuration
- `internationalization.py` - i18n settings (TIME_ZONE, LANGUAGE_CODE)
- `static.py` - Static files configuration
- `middleware.py` - Middleware configuration
- `templates.py` - Templates configuration
- `auth.py` - Authentication settings (AUTH_USER_MODEL, password validators)
- `external_services.py` - External services (OpenSearch, GEMI, AWS)
- `orchestrator.py` - Pipeline Orchestrator settings

## Usage

The settings are automatically imported when Django loads. The `__init__.py` file imports all modules in the correct order.

### Adding New Settings

1. Create a new file in this directory (e.g., `my_new_settings.py`)
2. Define your settings in that file
3. Import it in `__init__.py`:
   ```python
   from .my_new_settings import *
   ```

### Environment Variables

All environment variables are read from the system environment. See individual module files for specific environment variables.

## Migration from Single File

The original `settings.py` file has been refactored into this modular structure. The old file can be backed up or deleted after verifying the new structure works correctly.

## Notes

- The `__init__.py` file is the main entry point - Django will load this as the settings module
- Each module can import from other modules using relative imports (e.g., `from .base import DEBUG`)
- The order of imports in `__init__.py` matters - modules that depend on others must be imported after their dependencies
