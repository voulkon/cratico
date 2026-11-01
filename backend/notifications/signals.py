"""Create the default notification preference for every new user."""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from notifications.models import NotificationPreference


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_notification_preference(sender, instance, created, raw=False, **kwargs):
    """New users start on the documented digest defaults (§6.2).

    ``raw=True`` (loaddata/fixtures) must not touch related tables; the data
    migration creates rows for users that already exist on deploy.
    """
    if not created or raw:
        return
    NotificationPreference.objects.get_or_create(user=instance)
