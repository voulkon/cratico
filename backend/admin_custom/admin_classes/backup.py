from core.models import Backup
from core.services.database_stats_service import DatabaseStatsService
from core.tasks import create_backup_task, restore_backup_task
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html


class BackupAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "backup_type",
        "created_at",
        "status_badge",
        "task_state_display",
        "progress_display",
        "size_display",
        "s3_location",
        "streaming_method",
        "cancel_action",
    )
    list_filter = ("backup_type", "status", "created_at", "use_streaming")
    readonly_fields = (
        "status",
        "s3_key",
        "size_bytes",
        "logs_display",
        "snapshot_name",
        "created_at",
        "updated_at",
        "s3_full_path",
        "celery_task_id",
        "task_state_display",
    )
    actions = ["restore_backup", "cancel_backup_action"]
    change_list_template = "admin/backup_change_list.html"
    change_form_template = "admin/backup_change_form.html"

    def status_badge(self, obj):
        colors = {
            "pending": "#ffc107",
            "in_progress": "#2196F3",
            "success": "#4CAF50",
            "failed": "#f44336",
        }
        color = colors.get(obj.status, "#999")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"

    def task_state_display(self, obj):
        """Show the Celery task state for running backups"""
        if not obj.celery_task_id:
            return "-"

        from celery.result import AsyncResult
        from diavgeia_project.celery import app

        try:
            result = AsyncResult(obj.celery_task_id, app=app)
            state = result.state

            state_colors = {
                "PENDING": "#ffc107",
                "STARTED": "#2196F3",
                "RETRY": "#FF9800",
                "FAILURE": "#f44336",
                "SUCCESS": "#4CAF50",
                "REVOKED": "#9E9E9E",
            }
            color = state_colors.get(state, "#999")

            # For REVOKED state, show it clearly
            if state == "REVOKED":
                return format_html(
                    '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">[DENIED] CANCELLED</span>',
                    color,
                )

            return format_html(
                '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">{}</span>',
                color,
                state,
            )
        except Exception:
            return "-"

    task_state_display.short_description = "Task State"

    def progress_display(self, obj):
        """Extract and display latest progress from logs"""
        if obj.status not in [Backup.Status.PENDING, Backup.Status.IN_PROGRESS]:
            return "-"

        if not obj.logs:
            return format_html('<span style="color: #999;">Starting...</span>')

        # Extract latest progress info from logs
        import re

        # Look for "[EXPORT] Uploaded X MB..." pattern
        progress_pattern = r"[EXPORT] Uploaded (\d+\.\d+) MB"
        matches = re.findall(progress_pattern, obj.logs)

        if matches:
            latest_mb = matches[-1]  # Get the most recent progress
            return format_html(
                '<span style="color: #2196F3; font-weight: bold;">[EXPORT] {} MB</span>',
                latest_mb,
            )

        # Check for other status messages
        if "Starting streaming pg_dump" in obj.logs:
            return format_html(
                '<span style="color: #FF9800;">[RETRY] Streaming...</span>'
            )
        elif "Starting pg_dump" in obj.logs:
            return format_html('<span style="color: #FF9800;">[SAVE] Dumping...</span>')
        elif "Uploading to S3" in obj.logs:
            return format_html('<span style="color: #2196F3;">⬆️ Uploading...</span>')

        return format_html('<span style="color: #999;">In progress...</span>')

    progress_display.short_description = "Progress"

    def size_display(self, obj):
        if not obj.size_bytes:
            return "-"
        # Convert to human readable
        size = obj.size_bytes
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

    size_display.short_description = "Size"

    def s3_location(self, obj):
        if obj.backup_type == Backup.BackupType.POSTGRES and obj.s3_key:
            return format_html(
                '<code style="font-size: 11px;">{}</code>', obj.s3_key.split("/")[-1]
            )
        elif obj.backup_type == Backup.BackupType.OPENSEARCH and obj.snapshot_name:
            return format_html(
                '<code style="font-size: 11px;">{}</code>', obj.snapshot_name
            )
        return "-"

    s3_location.short_description = "S3/Snapshot Name"

    def streaming_method(self, obj):
        if obj.backup_type == Backup.BackupType.POSTGRES:
            return format_html(
                '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">{}</span>',
                "#2196F3" if obj.use_streaming else "#FF9800",
                "Streaming" if obj.use_streaming else "File-based",
            )
        return "-"

    streaming_method.short_description = "Method"

    def cancel_action(self, obj):
        if (
            obj.status in [Backup.Status.PENDING, Backup.Status.IN_PROGRESS]
            and obj.celery_task_id
        ):
            from django.urls import reverse

            url = reverse("admin:cancel_backup", args=[obj.id])
            return format_html(
                '<a href="{}" style="color: #f44336; font-weight: bold;" onclick="return confirm(\'Are you sure you want to cancel this backup?\')">Cancel</a>',
                url,
            )
        return "-"

    cancel_action.short_description = "Action"

    def s3_full_path(self, obj):
        from django.conf import settings

        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "diavgeia-backups")
        if obj.backup_type == Backup.BackupType.POSTGRES and obj.s3_key:
            return format_html(
                's3://{}/{}<br><small style="color: #666;">Full S3 URI</small>',
                bucket,
                obj.s3_key,
            )
        elif obj.backup_type == Backup.BackupType.OPENSEARCH and obj.snapshot_name:
            return format_html(
                's3://{}/backups/opensearch/{}<br><small style="color: #666;">Snapshot stored in S3-backed repository</small>',
                bucket,
                obj.snapshot_name,
            )
        return "Not yet uploaded"

    s3_full_path.short_description = "Full S3 Path"

    def logs_display(self, obj):
        if not obj.logs:
            return format_html('<em style="color: #999;">No logs yet</em>')
        return format_html(
            '<pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; max-height: 400px; overflow-y: auto; font-size: 12px;">{}</pre>',
            obj.logs,
        )

    logs_display.short_description = "Logs"

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path(
                "stats/",
                self.admin_site.admin_view(self.stats_view),
                name="backup_stats",
            ),
            path(
                "trigger-postgres/",
                self.admin_site.admin_view(self.trigger_postgres_backup),
                name="trigger_postgres_backup",
            ),
            path(
                "trigger-opensearch/",
                self.admin_site.admin_view(self.trigger_opensearch_backup),
                name="trigger_opensearch_backup",
            ),
            path(
                "browse-s3/",
                self.admin_site.admin_view(self.browse_s3),
                name="browse_s3",
            ),
            path(
                "restore-from-s3-postgres/<path:s3_key>/",
                self.admin_site.admin_view(self.restore_postgres_from_s3),
                name="restore_postgres_from_s3",
            ),
            path(
                "restore-from-s3-opensearch/<str:snapshot_name>/",
                self.admin_site.admin_view(self.restore_opensearch_from_s3),
                name="restore_opensearch_from_s3",
            ),
            path(
                "<int:backup_id>/cancel/",
                self.admin_site.admin_view(self.cancel_backup),
                name="cancel_backup",
            ),
        ]
        return my_urls + urls

    def stats_view(self, request):
        from django.conf import settings

        from core.services.opensearch_service import OpenSearchService

        service = DatabaseStatsService()

        opensearch_stats = None
        opensearch_enabled = False
        if settings.INDEX_THE_OPENSEARCH:
            opensearch_service = OpenSearchService()
            opensearch_enabled = opensearch_service.is_enabled
            if opensearch_enabled:
                opensearch_stats = service.get_opensearch_stats()

        context = dict(
            self.admin_site.each_context(request),
            postgres_stats=service.get_postgres_stats(),
            opensearch_stats=opensearch_stats,
            opensearch_enabled=opensearch_enabled,
            title="Database Statistics",
        )
        return TemplateResponse(request, "admin/backup_stats.html", context)

    def save_model(self, request, obj, form, change):
        if not change:  # Creating new object
            super().save_model(request, obj, form, change)
            # Trigger the backup task
            create_backup_task.delay(obj.id)
            messages.info(
                request, f"Backup process started for {obj.get_backup_type_display()}."
            )
        else:
            super().save_model(request, obj, form, change)

    def trigger_postgres_backup(self, request):
        use_streaming = request.GET.get("streaming", "true").lower() == "true"
        backup = Backup.objects.create(
            backup_type=Backup.BackupType.POSTGRES,
            status=Backup.Status.PENDING,
            use_streaming=use_streaming,
        )
        task = create_backup_task.delay(backup.id)
        backup.celery_task_id = task.id
        backup.save()
        method = "streaming" if use_streaming else "file-based"
        self.message_user(
            request,
            f"PostgreSQL backup #{backup.id} started ({method}). Monitor progress in the backup list.",
            messages.SUCCESS,
        )
        return redirect("admin:core_backup_changelist")

    def trigger_opensearch_backup(self, request):
        from django.conf import settings

        if not settings.INDEX_THE_OPENSEARCH:
            self.message_user(
                request,
                "OpenSearch is disabled (INDEX_THE_OPENSEARCH=false). Cannot create OpenSearch backup.",
                messages.ERROR,
            )
            return redirect("admin:core_backup_changelist")

        backup = Backup.objects.create(
            backup_type=Backup.BackupType.OPENSEARCH, status=Backup.Status.PENDING
        )
        task = create_backup_task.delay(backup.id)
        backup.celery_task_id = task.id
        backup.save()
        self.message_user(
            request,
            f"OpenSearch backup #{backup.id} started. Monitor progress in the backup list.",
            messages.SUCCESS,
        )
        return redirect("admin:core_backup_changelist")

    def cancel_backup(self, request, backup_id):
        """Cancel a running backup task"""
        try:
            backup = Backup.objects.get(id=backup_id)

            if backup.status not in [Backup.Status.PENDING, Backup.Status.IN_PROGRESS]:
                self.message_user(
                    request,
                    f"Cannot cancel backup #{backup_id} - status is {backup.get_status_display()}",
                    messages.ERROR,
                )
                return redirect("admin:core_backup_changelist")

            if not backup.celery_task_id:
                self.message_user(
                    request,
                    f"Cannot cancel backup #{backup_id} - no task ID found",
                    messages.ERROR,
                )
                return redirect("admin:core_backup_changelist")

            # Revoke the Celery task
            from celery.result import AsyncResult
            from diavgeia_project.celery import app

            result = AsyncResult(backup.celery_task_id, app=app)
            task_state_before = result.state
            result.revoke(
                terminate=True, signal="SIGKILL"
            )  # Use SIGKILL for forceful termination

            # Update backup status
            backup.status = Backup.Status.FAILED
            backup.logs += f"\n{'='*60}\n"
            backup.logs += f"[{timezone.now()}] [DENIED] BACKUP CANCELLED BY USER\n"
            backup.logs += f"Task state before cancellation: {task_state_before}\n"
            backup.logs += f"Task revoked with SIGKILL signal\n"
            backup.logs += f"{'='*60}\n"
            backup.save()

            # Wait a moment and check if revocation was successful
            import time

            time.sleep(0.5)
            task_state_after = result.state

            if task_state_after == "REVOKED":
                self.message_user(
                    request,
                    f"[OK] Backup #{backup_id} has been successfully cancelled (Task state: {task_state_after})",
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"[WARN]️ Cancellation signal sent to backup #{backup_id}. Task state: {task_state_after}. Check logs for confirmation.",
                    messages.WARNING,
                )

        except Backup.DoesNotExist:
            self.message_user(request, f"Backup #{backup_id} not found", messages.ERROR)
        except Exception as e:
            self.message_user(
                request, f"Error cancelling backup: {str(e)}", messages.ERROR
            )

        return redirect("admin:core_backup_changelist")

    @admin.action(description="Cancel selected backup(s)")
    def cancel_backup_action(self, request, queryset):
        """Admin action to cancel multiple backups"""
        from celery.result import AsyncResult
        from diavgeia_project.celery import app

        cancelled = 0
        errors = []

        for backup in queryset:
            if backup.status not in [Backup.Status.PENDING, Backup.Status.IN_PROGRESS]:
                errors.append(
                    f"Backup #{backup.id}: Cannot cancel - status is {backup.get_status_display()}"
                )
                continue

            if not backup.celery_task_id:
                errors.append(f"Backup #{backup.id}: No task ID found")
                continue

            try:
                result = AsyncResult(backup.celery_task_id, app=app)
                task_state_before = result.state
                result.revoke(terminate=True, signal="SIGKILL")

                backup.status = Backup.Status.FAILED
                backup.logs += f"\n{'='*60}\n"
                backup.logs += f"[{timezone.now()}] [DENIED] BACKUP CANCELLED BY USER (bulk action)\n"
                backup.logs += f"Task state before cancellation: {task_state_before}\n"
                backup.logs += f"Task revoked with SIGKILL signal\n"
                backup.logs += f"{'='*60}\n"
                backup.save()

                cancelled += 1
            except Exception as e:
                errors.append(f"Backup #{backup.id}: {str(e)}")

        if cancelled:
            self.message_user(
                request,
                f"[OK] Successfully cancelled {cancelled} backup(s)",
                messages.SUCCESS,
            )
        if errors:
            for error in errors:
                self.message_user(request, error, messages.WARNING)

    def browse_s3(self, request):
        """Browse S3 backups"""
        import boto3
        from botocore.exceptions import ClientError
        from django.conf import settings

        bucket_name = settings.AWS_STORAGE_BUCKET_NAME

        # Check if AWS credentials are configured
        aws_access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
        aws_secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)

        errors = []

        if not aws_access_key or not aws_secret_key:
            errors.append(
                "AWS credentials not configured. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in settings."
            )
            context = dict(
                self.admin_site.each_context(request),
                s3_files={"postgres": [], "opensearch": []},
                bucket_name=bucket_name,
                errors=errors,
                title="Browse S3 Backups",
            )
            return TemplateResponse(request, "admin/browse_s3.html", context)

        s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=settings.AWS_S3_REGION_NAME,
        )

        s3_files = {"postgres": [], "opensearch": []}
        errors = []

        try:
            # List PostgreSQL backups
            response = s3_client.list_objects_v2(
                Bucket=bucket_name, Prefix="backups/postgres/"
            )
            if "Contents" in response:
                for obj in response["Contents"]:
                    if obj["Key"].endswith(".dump"):
                        s3_files["postgres"].append(
                            {
                                "key": obj["Key"],
                                "size": obj["Size"],
                                "last_modified": obj["LastModified"],
                                "filename": obj["Key"].split("/")[-1],
                            }
                        )
        except ClientError as e:
            errors.append(f"Error listing PostgreSQL backups: {str(e)}")

        # Only list OpenSearch snapshots if OpenSearch is enabled
        if settings.INDEX_THE_OPENSEARCH:
            try:
                # List OpenSearch snapshots using OpenSearch API
                # This ensures we get the actual snapshot names that were created
                from core.services.opensearch_service import OpenSearchService

                opensearch_service = OpenSearchService()

                # First ensure repository is registered
                try:
                    opensearch_service.register_s3_repository(
                        repository_name="s3-backup-repo",
                        bucket_name=bucket_name,
                        base_path="backups/opensearch",
                    )
                except Exception as reg_error:
                    errors.append(
                        f"Warning: Could not register S3 repository: {str(reg_error)}"
                    )

                # List snapshots from OpenSearch
                snapshots = opensearch_service.list_snapshots(
                    repository_name="s3-backup-repo"
                )

                for snapshot in snapshots:
                    # OpenSearch returns snapshot metadata including name, state, timestamp, etc.
                    s3_files["opensearch"].append(
                        {
                            "snapshot_name": snapshot.get("snapshot", "Unknown"),
                            "state": snapshot.get("state", "UNKNOWN"),
                            "start_time": snapshot.get("start_time_in_millis", 0),
                            "last_modified": (
                                timezone.datetime.fromtimestamp(
                                    snapshot.get("start_time_in_millis", 0) / 1000
                                )
                                if snapshot.get("start_time_in_millis")
                                else None
                            ),
                            "size": snapshot.get("shards", {}).get("total", 0),
                            "indices": ", ".join(snapshot.get("indices", [])),
                            "uuid": snapshot.get("uuid", "N/A"),
                        }
                    )

            except Exception as e:
                errors.append(f"Error listing OpenSearch snapshots: {str(e)}")
        else:
            errors.append(
                "OpenSearch is disabled (INDEX_THE_OPENSEARCH=false). OpenSearch snapshots not available."
            )

        context = dict(
            self.admin_site.each_context(request),
            s3_files=s3_files,
            bucket_name=bucket_name,
            errors=errors,
            title="Browse S3 Backups",
        )
        return TemplateResponse(request, "admin/browse_s3.html", context)

    @admin.action(description="Restore selected backup")
    def restore_backup(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Please select exactly one backup to restore.",
                messages.WARNING,
            )
            return

        backup = queryset.first()
        if backup.status != Backup.Status.SUCCESS:
            self.message_user(
                request, "Can only restore successful backups.", messages.ERROR
            )
            return

        restore_backup_task.delay(backup.id)
        self.message_user(
            request, f"Restore process started for {backup}.", messages.SUCCESS
        )

    def restore_postgres_from_s3(self, request, s3_key):
        """Restore a PostgreSQL backup directly from S3"""
        try:
            # Create a new Backup record to track the restore operation
            backup = Backup.objects.create(
                backup_type=Backup.BackupType.POSTGRES,
                status=Backup.Status.SUCCESS,  # Mark as success since file exists in S3
                s3_key=s3_key,
                logs=f"Backup imported from S3: {s3_key}\n",
            )

            # Trigger restore task
            restore_backup_task.delay(backup.id)
            self.message_user(
                request,
                f"PostgreSQL restore started from S3: {s3_key.split('/')[-1]}. Monitor progress in the backup list.",
                messages.SUCCESS,
            )
        except Exception as e:
            self.message_user(
                request, f"Failed to start restore: {str(e)}", messages.ERROR
            )
        return redirect("admin:browse_s3")

    def restore_opensearch_from_s3(self, request, snapshot_name):
        """Restore an OpenSearch snapshot directly from S3"""
        from django.conf import settings

        if not settings.INDEX_THE_OPENSEARCH:
            self.message_user(
                request,
                "OpenSearch is disabled (INDEX_THE_OPENSEARCH=false). Cannot restore OpenSearch backup.",
                messages.ERROR,
            )
            return redirect("admin:browse_s3")

        try:
            # Create a new Backup record to track the restore operation
            backup = Backup.objects.create(
                backup_type=Backup.BackupType.OPENSEARCH,
                status=Backup.Status.SUCCESS,  # Mark as success since snapshot exists in S3
                snapshot_name=snapshot_name,
                logs=f"Snapshot imported from S3: {snapshot_name}\n",
            )

            # Trigger restore task
            restore_backup_task.delay(backup.id)
            self.message_user(
                request,
                f"OpenSearch restore started from snapshot: {snapshot_name}. Monitor progress in the backup list.",
                messages.SUCCESS,
            )
        except Exception as e:
            self.message_user(
                request, f"Failed to start restore: {str(e)}", messages.ERROR
            )
        return redirect("admin:browse_s3")
