"""
URL configuration for diavgeia_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from admin_custom.sites import admin_site
from api.views.version import version_check
from diavgeia_project.settings.base import ENABLE_SILK
from django.urls import include, path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

# Define schema_view FIRST before using it
# Note: API docs should always be publicly accessible
# If you need to restrict access, add /api/docs/ to stealth mode exempt list
schema_view = get_schema_view(
    openapi.Info(
        title="Crati API",
        default_version="v1",
        description="API for searching and processing Greek government decisions",
        contact=openapi.Contact(email="contact@crati.app"),
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
)

GLOBAL_URL_PREFIX = "api/"

# Then define your urlpatterns (just once, not twice!)
urlpatterns = [
    path(f"{GLOBAL_URL_PREFIX}admin/", admin_site.urls),
    path(f"{GLOBAL_URL_PREFIX}version/", version_check, name="health_check"),
    # TODO: Make a full health check that will be notifying about its dependenecies (DB, Redis, etc.) and use it in the root path for uptime monitoring
    path(f"{GLOBAL_URL_PREFIX}", version_check, name="root_health_check"),
    path(f"{GLOBAL_URL_PREFIX}", include("api.urls")),
    path(
        f"{GLOBAL_URL_PREFIX}docs/",
        csrf_exempt(never_cache(schema_view.with_ui("swagger", cache_timeout=0))),
        name="schema-swagger-ui",
    ),
    path(
        f"{GLOBAL_URL_PREFIX}redoc/",
        csrf_exempt(never_cache(schema_view.with_ui("redoc", cache_timeout=0))),
        name="schema-redoc",
    ),
]

if ENABLE_SILK:
    urlpatterns += [
        path(f"{GLOBAL_URL_PREFIX}silk/", include("silk.urls", namespace="silk")),
    ]
