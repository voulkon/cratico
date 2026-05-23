from celery import shared_task


@shared_task
def persist_analytics_task():
    """Task to persist Redis analytics data to database"""
    from django.core import management

    management.call_command("persist_analytics")
    return True
