import os
import sys

# Only import Celery if we're running a Celery worker, not Django
if "celery" in sys.argv or "worker" in sys.argv or os.environ.get("CELERY_WORKER"):
    from .celery import app as celery_app

    __all__ = ("celery_app",)
else:
    # For Django processes, don't import Celery
    celery_app = None
    __all__ = ()
