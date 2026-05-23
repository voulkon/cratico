import os
import subprocess

import boto3
from core.models import Backup
from core.services.opensearch_service import OpenSearchService
from django.conf import settings
from django.utils import timezone
from loguru import logger


class BackupService:
    def __init__(
        self,
        aws_access_key=None,
        aws_secret_key=None,
        bucket_name=None,
        region_name=None,
    ):
        """Initialize BackupService with AWS credentials.

        Args:
            aws_access_key: AWS access key ID (defaults to settings.AWS_ACCESS_KEY_ID)
            aws_secret_key: AWS secret access key (defaults to settings.AWS_SECRET_ACCESS_KEY)
            bucket_name: S3 bucket name (defaults to settings.AWS_STORAGE_BUCKET_NAME)
            region_name: AWS region (defaults to settings.AWS_S3_REGION_NAME)

        Raises:
            ValueError: If required credentials are not provided
        """
        # Use provided values or fall back to settings
        self.aws_access_key = aws_access_key or settings.AWS_ACCESS_KEY_ID
        self.aws_secret_key = aws_secret_key or settings.AWS_SECRET_ACCESS_KEY
        self.bucket_name = bucket_name or settings.AWS_STORAGE_BUCKET_NAME
        self.region_name = region_name or settings.AWS_S3_REGION_NAME

        # Validate required parameters
        if not self.aws_access_key:
            raise ValueError(
                "AWS_ACCESS_KEY_ID is required. Set it in Django settings or pass as parameter."
            )
        if not self.aws_secret_key:
            raise ValueError(
                "AWS_SECRET_ACCESS_KEY is required. Set it in Django settings or pass as parameter."
            )
        if not self.bucket_name:
            raise ValueError(
                "AWS_STORAGE_BUCKET_NAME is required. Set it in Django settings or pass as parameter."
            )
        if not self.region_name:
            raise ValueError(
                "AWS_S3_REGION_NAME is required. Set it in Django settings or pass as parameter."
            )

        # Initialize S3 client
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=self.aws_access_key,
            aws_secret_access_key=self.aws_secret_key,
            region_name=self.region_name,
        )

        # Validate credentials before proceeding
        self._validate_credentials()

        # Initialize OpenSearch service
        if settings.INDEX_THE_OPENSEARCH:
            self.opensearch_service = OpenSearchService()

        # Ensure bucket exists
        self._ensure_bucket_exists()

    def _validate_credentials(self):
        """Validate AWS credentials by checking access to the specific bucket.

        This is optional - if we lack GetBucketLocation permission, we skip validation
        and trust that actual backup operations (PutObject) will work.

        Raises:
            ValueError: If credentials are definitely invalid (wrong key/signature)
        """
        from botocore.exceptions import ClientError, NoCredentialsError

        try:
            # Try to get bucket location - requires s3:GetBucketLocation on the specific bucket
            # This validates credentials without requiring global ListAllMyBuckets permission
            self.s3_client.get_bucket_location(Bucket=self.bucket_name)
            logger.info(
                f"[OK] AWS credentials validated - have access to bucket '{self.bucket_name}'"
            )
        except NoCredentialsError:
            raise ValueError(
                "AWS credentials not found. Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "InvalidAccessKeyId":
                raise ValueError(f"Invalid AWS Access Key ID")
            elif error_code == "SignatureDoesNotMatch":
                raise ValueError("Invalid AWS Secret Access Key (signature mismatch)")
            elif error_code == "NoSuchBucket":
                # Bucket doesn't exist yet - credentials are valid
                logger.info(
                    f"[OK] AWS credentials valid (bucket '{self.bucket_name}' doesn't exist yet)"
                )
            elif error_code == "AccessDenied" or error_code == "Forbidden":
                # Limited permissions - can't validate, but actual backup ops might work
                logger.warning(
                    f"[WARN]️ Cannot validate bucket access (need s3:GetBucketLocation). Will attempt backup anyway."
                )
            else:
                logger.warning(
                    f"[WARN]️ Could not validate credentials: {e}. Will attempt backup anyway."
                )

    def _ensure_bucket_exists(self):
        """Check if S3 bucket exists, create if possible.

        This is best-effort - if we lack permissions, we assume bucket exists
        and let actual backup operations fail with clear errors if it doesn't.
        """
        from botocore.exceptions import ClientError

        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"[OK] S3 bucket '{self.bucket_name}' exists")
        except ClientError as e:
            error_code = e.response["Error"]["Code"]

            if error_code == "404" or error_code == "NoSuchBucket":
                # Bucket doesn't exist, try to create it
                logger.info(
                    f"[PKG] Bucket '{self.bucket_name}' doesn't exist, attempting to create..."
                )
                try:
                    # For us-east-1, don't specify LocationConstraint (AWS API quirk)
                    # https://docs.aws.amazon.com/AmazonS3/latest/API/API_CreateBucket.html
                    if self.region_name == "us-east-1":
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={
                                "LocationConstraint": self.region_name
                            },
                        )
                    logger.info(
                        f"[OK] Created S3 bucket '{self.bucket_name}' in {self.region_name}"
                    )
                except ClientError as create_error:
                    create_code = create_error.response["Error"]["Code"]
                    if create_code == "BucketAlreadyOwnedByYou":
                        logger.info(f"[OK] Bucket '{self.bucket_name}' already exists")
                    elif create_code == "BucketAlreadyExists":
                        raise ValueError(
                            f"Bucket '{self.bucket_name}' already exists and is owned by another account"
                        )
                    elif create_code == "AccessDenied":
                        logger.warning(
                            f"[WARN]️ Cannot create bucket (need s3:CreateBucket). Assuming it exists - backup will fail if it doesn't."
                        )
                    else:
                        logger.warning(
                            f"[WARN]️ Could not create bucket: {create_error}. Assuming it exists."
                        )

            elif error_code == "403" or error_code == "Forbidden":
                # Can't check if bucket exists due to permissions
                logger.warning(
                    f"[WARN]️ Cannot check if bucket exists (limited permissions). Assuming '{self.bucket_name}' exists."
                )

            else:
                logger.warning(
                    f"[WARN]️ Could not verify bucket: {e}. Will attempt backup anyway."
                )

    def create_postgres_backup(self, backup_id, use_streaming=False):
        """Create PostgreSQL backup.

        Args:
            backup_id: The ID of the Backup model instance
            use_streaming: If True, stream directly to S3 without saving to disk (recommended for low disk space)
        """
        backup = Backup.objects.get(id=backup_id)
        backup.status = Backup.Status.IN_PROGRESS
        backup.logs += "Starting PostgreSQL backup...\n"
        backup.save()

        local_path = None
        try:
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
            filename = f"postgres_backup_{timestamp}.dump"
            s3_key = f"backups/postgres/{filename}"

            # PG Dump
            # Using custom format (-Fc) which is compressed and allows selective restore
            db_settings = settings.DATABASES["default"]
            env = os.environ.copy()
            env["PGPASSWORD"] = db_settings["PASSWORD"]

            cmd = [
                "pg_dump",
                "-h",
                db_settings["HOST"],
                "-p",
                str(db_settings["PORT"]),
                "-U",
                db_settings["USER"],
                "-d",
                db_settings["NAME"],
                "-F",
                "c",  # Custom format
            ]

            if use_streaming:
                # STREAMING METHOD: Pipe directly to S3 without saving to disk
                logger.info(f"Starting streaming pg_dump to S3: {s3_key}")
                backup.logs += (
                    f"Starting streaming pg_dump to S3 (no local disk usage)...\n"
                )
                backup.save()

                # Run pg_dump and capture stdout
                process = subprocess.Popen(
                    cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )

                # Progress tracking
                bytes_uploaded = [0]  # Use list to allow mutation in nested function
                last_log_time = [timezone.now()]

                def progress_callback(bytes_transferred):
                    """Update progress in logs every 10MB or 10 seconds"""
                    bytes_uploaded[0] += bytes_transferred
                    now = timezone.now()

                    # Log every 10MB or every 10 seconds
                    if (
                        bytes_uploaded[0] % (10 * 1024 * 1024) < bytes_transferred
                        or (now - last_log_time[0]).total_seconds() >= 10
                    ):
                        mb_uploaded = bytes_uploaded[0] / (1024 * 1024)
                        backup.logs += f"[EXPORT] Uploaded {mb_uploaded:.1f} MB...\n"
                        backup.save()
                        last_log_time[0] = now
                        logger.info(
                            f"Streaming backup {backup_id}: {mb_uploaded:.1f} MB uploaded"
                        )

                # Stream to S3 using upload_fileobj
                try:
                    self.s3_client.upload_fileobj(
                        process.stdout,
                        self.bucket_name,
                        s3_key,
                        Callback=progress_callback,
                    )

                    # Wait for process to complete and check for errors
                    _, stderr = process.communicate()

                    if process.returncode != 0:
                        error_msg = (
                            f"pg_dump failed with exit code {process.returncode}"
                        )
                        if stderr:
                            error_msg += f": {stderr.decode('utf-8', errors='replace')}"
                        raise subprocess.CalledProcessError(
                            process.returncode, cmd, stderr=stderr
                        )

                    if stderr:
                        backup.logs += f"pg_dump warnings: {stderr.decode('utf-8', errors='replace')}\n"
                        backup.save()

                    # Get file size from S3
                    response = self.s3_client.head_object(
                        Bucket=self.bucket_name, Key=s3_key
                    )
                    file_size = response["ContentLength"]

                    backup.s3_key = s3_key
                    backup.size_bytes = file_size
                    backup.status = Backup.Status.SUCCESS
                    backup.logs += (
                        f"[OK] Streaming backup successful! Size: {file_size} bytes\n"
                    )
                    backup.save()

                    logger.info(
                        f"[OK] PostgreSQL streaming backup {backup_id} completed successfully"
                    )

                except Exception:
                    # Kill the process if upload fails
                    process.kill()
                    raise
            else:
                # TRADITIONAL METHOD: Save to /tmp then upload
                local_path = f"/tmp/{filename}"
                cmd.extend(["-f", local_path])

                logger.info(f"Starting pg_dump to {local_path}")
                backup.logs += f"Running pg_dump to {local_path}...\n"
                backup.save()

                result = subprocess.run(
                    cmd, env=env, check=True, capture_output=True, text=True
                )  # nosec: B108 - Controlled path in /tmp directory

                if result.stderr:
                    backup.logs += f"pg_dump warnings: {result.stderr}\n"
                    backup.save()

                file_size = os.path.getsize(local_path)
                backup.logs += f"[OK] Dump completed. Size: {file_size} bytes\n"
                backup.save()

                # Upload to S3
                logger.info(f"Uploading to S3: {s3_key}")
                backup.logs += f"Uploading to S3: s3://{self.bucket_name}/{s3_key}...\n"
                backup.save()

                self.s3_client.upload_file(local_path, self.bucket_name, s3_key)

                # Update backup record
                backup.s3_key = s3_key
                backup.size_bytes = file_size
                backup.status = Backup.Status.SUCCESS
                backup.logs += f"[OK] Backup successful! Uploaded to S3.\n"
                backup.save()

                logger.info(
                    f"[OK] PostgreSQL backup {backup_id} completed successfully"
                )

        except subprocess.CalledProcessError as e:
            error_msg = f"pg_dump failed with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr}"
            logger.error(f"[ERROR] {error_msg}")
            backup.status = Backup.Status.FAILED
            backup.logs += f"[ERROR] {error_msg}\n"
            backup.save()
            raise
        except Exception as e:
            logger.error(
                f"[ERROR] PostgreSQL backup failed for backup {backup_id}: {e}"
            )
            backup.status = Backup.Status.FAILED
            backup.logs += f"[ERROR] Error: {str(e)}\n"
            backup.save()
            raise
        finally:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"Cleaned up temporary file: {local_path}")

    def restore_postgres_backup(self, backup_id):
        backup = Backup.objects.get(id=backup_id)
        # We don't change status to IN_PROGRESS here immediately because this might be called from a task
        # But let's assume the caller handles the initial status update or we do it here.

        local_path = None
        try:
            filename = os.path.basename(backup.s3_key)
            local_path = f"/tmp/{filename}"

            logger.info(f"Downloading from S3: {backup.s3_key}")
            self.s3_client.download_file(
                self.bucket_name, backup.s3_key, local_path
            )  # nosec: B108 - Controlled path in /tmp directory

            db_settings = settings.DATABASES["default"]
            env = os.environ.copy()
            env["PGPASSWORD"] = db_settings["PASSWORD"]

            # PG Restore
            # --clean: clean (drop) database objects before recreating them
            # --if-exists: used with --clean
            # --no-owner: do not output commands to set ownership of objects to match the original database
            # --no-privileges: do not output commands to grant access privileges
            cmd = [
                "pg_restore",
                "-h",
                db_settings["HOST"],
                "-p",
                str(db_settings["PORT"]),
                "-U",
                db_settings["USER"],
                "-d",
                db_settings["NAME"],
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                local_path,
            ]

            logger.info(f"Starting pg_restore from {local_path}")
            subprocess.run(cmd, env=env, check=True)

            logger.info("Restore successful")
            return True, "Restore successful"

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False, str(e)
        finally:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)

    def create_opensearch_snapshot(self, backup_id):
        if not settings.INDEX_THE_OPENSEARCH:
            logger.info(
                "OpenSearch indexing is disabled in settings. Skipping snapshot."
            )
            return
        backup = Backup.objects.get(id=backup_id)
        backup.status = Backup.Status.IN_PROGRESS
        backup.logs += "Starting OpenSearch snapshot...\n"
        backup.save()

        try:
            timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
            snapshot_name = f"snapshot-{timestamp}"
            repo_name = "s3-backup-repo"

            # Step 1: Register repository
            backup.logs += f"Registering S3 repository '{repo_name}'...\n"
            backup.save()

            register_result = self.opensearch_service.register_s3_repository(
                repository_name=repo_name,
                bucket_name=self.bucket_name,
                base_path="backups/opensearch",
            )

            if not register_result:
                raise Exception("Failed to register S3 repository")

            backup.logs += "Repository registered successfully.\n"
            backup.save()

            # Step 2: Create snapshot
            backup.logs += f"Creating snapshot '{snapshot_name}'...\n"
            backup.save()

            result = self.opensearch_service.create_snapshot(
                repository_name=repo_name, snapshot_name=snapshot_name
            )

            # Check result - create_snapshot now raises exceptions on failure
            if result.get("success"):
                backup.snapshot_name = snapshot_name
                backup.status = Backup.Status.SUCCESS
                backup.logs += f"[OK] Snapshot {snapshot_name} created successfully.\n"
                backup.save()
                logger.info(
                    f"[OK] OpenSearch backup {backup_id} completed successfully"
                )
            else:
                # This shouldn't happen now since we raise exceptions, but keep as safeguard
                error = result.get("error", "Unknown error")
                raise Exception(f"Snapshot creation returned failure: {error}")

        except Exception as e:
            logger.error(
                f"[ERROR] OpenSearch snapshot failed for backup {backup_id}: {e}"
            )
            backup.status = Backup.Status.FAILED
            backup.logs += f"[ERROR] Error: {str(e)}\n"
            backup.save()
            # Re-raise to let Celery know the task failed
            raise

    def restore_opensearch_snapshot(self, backup_id):
        if not settings.INDEX_THE_OPENSEARCH:
            logger.info(
                "OpenSearch indexing is disabled in settings. Skipping restore."
            )
            return
        backup = Backup.objects.get(id=backup_id)

        try:
            repo_name = "s3-backup-repo"
            # Ensure repo is registered (idempotent usually)
            self.opensearch_service.register_s3_repository(
                repository_name=repo_name,
                bucket_name=self.bucket_name,
                base_path="backups/opensearch",
            )

            self.opensearch_service.restore_snapshot(
                repository_name=repo_name, snapshot_name=backup.snapshot_name
            )
            return True, "Restore started successfully"
        except Exception as e:
            return False, str(e)
