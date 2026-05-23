from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import core.signals  # noqa

        # ("Core app is ready and signals are imported.")
        # Note: Feature flag initialization removed from AppConfig.ready()
        # to comply with Django best practices (no database access during app init).
        # Feature flags are created lazily on first use by the feature_flag_service,
        # or you can explicitly initialize them with: python manage.py initialize_feature_flags
