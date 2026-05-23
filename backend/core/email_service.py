"""
Centralized email service for the application.

Provides reusable email sending functionality for:
- User registration and account verification
- Notification digests
- Password reset
- Other transactional emails
"""

from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from loguru import logger


class EmailService:
    """
    Centralized service for sending emails.

    All email sending should go through this service to ensure
    consistency, proper error handling, and easier testing.
    """

    DEFAULT_FROM_EMAIL = settings.DEFAULT_FROM_EMAIL

    @staticmethod
    def send_email(
        subject: str,
        to_emails: List[str],
        html_content: str,
        text_content: Optional[str] = None,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to: Optional[List[str]] = None,
        attachments: Optional[List[tuple]] = None,
    ) -> bool:
        """
        Send an email with both HTML and plain text versions.

        Args:
            subject: Email subject line
            to_emails: List of recipient email addresses
            html_content: HTML version of the email body
            text_content: Plain text version (auto-generated from HTML if not provided)
            from_email: Sender email address (uses DEFAULT_FROM_EMAIL if not provided)
            cc: List of CC recipients
            bcc: List of BCC recipients
            reply_to: List of reply-to addresses
            attachments: List of tuples (filename, content, mimetype)

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        if not to_emails:
            logger.warning("Attempted to send email with no recipients")
            return False

        # Auto-generate text content from HTML if not provided
        if text_content is None:
            text_content = strip_tags(html_content)

        # Use default from_email if not specified
        from_email = from_email or EmailService.DEFAULT_FROM_EMAIL

        try:
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=to_emails,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
            )

            # Attach HTML alternative
            email.attach_alternative(html_content, "text/html")

            # Add any attachments
            if attachments:
                for filename, content, mimetype in attachments:
                    email.attach(filename, content, mimetype)

            email.send(fail_silently=False)

            logger.debug(f"Email sent successfully: '{subject}' to {to_emails}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email '{subject}' to {to_emails}: {str(e)}")
            return False

    @staticmethod
    def send_template_email(
        subject: str,
        to_emails: List[str],
        template_name: str,
        context: Dict[str, Any],
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        language: Optional[str] = None,
    ) -> bool:
        """
        Send an email using a Django template with optional language support.

        Args:
            subject: Email subject line
            to_emails: List of recipient email addresses
            template_name: Name of the template (e.g., 'emails/welcome.html' or 'emails/welcome.en.html')
            context: Dictionary of context variables for the template
            from_email: Sender email address
            cc: List of CC recipients
            bcc: List of BCC recipients
            language: Language code (e.g., 'en', 'el'). If provided, will use language-specific template.

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # If language is specified and template doesn't already have language suffix,
            # try to use the language-specific version
            if language and not any(
                template_name.endswith(f".{lang}.html") for lang in ["en", "el"]
            ):
                # Insert language code before .html extension
                lang_template = template_name.replace(".html", f".{language}.html")
                # Try to use language-specific template, fall back to default
                try:
                    html_content = render_to_string(lang_template, context)
                    template_name = lang_template  # Use for text template lookup
                except Exception:
                    logger.debug(
                        f"Language-specific template '{lang_template}' not found, using default"
                    )
                    html_content = render_to_string(template_name, context)
            else:
                # Render HTML version
                html_content = render_to_string(template_name, context)

            # Try to render text version if it exists
            text_template = template_name.replace(".html", ".txt")
            try:
                text_content = render_to_string(text_template, context)
            except Exception:
                # Text template doesn't exist, will auto-generate from HTML
                text_content = None

            return EmailService.send_email(
                subject=subject,
                to_emails=to_emails,
                html_content=html_content,
                text_content=text_content,
                from_email=from_email,
                cc=cc,
                bcc=bcc,
            )

        except Exception as e:
            logger.error(f"Failed to render email template '{template_name}': {str(e)}")
            return False


class RegistrationEmailService:
    """
    Service for Django native registration emails (optional).

    Only needed if you want email verification for Django-registered users.
    Clerk handles all this for Clerk-authenticated users automatically.
    """

    frontend_url = (
        settings.FRONTEND_HOSTNAMES[0]
        if settings.FRONTEND_HOSTNAMES
        else "https://crati.co"
    )

    @staticmethod
    def send_verification_email(
        user_email: str, username: str, verification_token: str
    ) -> bool:
        """
        Send email verification link to newly registered Django user.

        For Clerk users, Clerk handles verification automatically.
        """
        from django.conf import settings

        app_name = getattr(settings, "APP_NAME", "Crati.Co")

        verification_url = f"{RegistrationEmailService.frontend_url}/verify-email?token={verification_token}"

        subject = f"Verify your {app_name} email address"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333333; background-color: #f5f5f5;">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin: 0; padding: 20px; background-color: #f5f5f5;">
                <tr>
                    <td align="center">
                        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width: 600px; margin: 0 auto;">
                            <!-- Header -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">✨ Verify Your Email</h1>
                                </td>
                            </tr>
                            <!-- Content -->
                            <tr>
                                <td style="background: #ffffff; padding: 30px; border-left: 1px solid #e0e0e0; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0;">
                                    <h2 style="margin: 0 0 16px 0; color: #333333; font-size: 20px;">Welcome to {app_name}, {username}!</h2>
                                    <p style="margin: 0 0 24px 0; color: #333333; font-size: 16px; line-height: 1.6;">Thank you for creating an account. To get started, please verify your email address by clicking the button below:</p>

                                    <!-- Button with proper email client compatibility -->
                                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin: 24px 0;">
                                        <tr>
                                            <td align="center">
                                                <a href="{verification_url}" target="_blank" style="display: inline-block; padding: 14px 32px; background-color: #667eea; color: #ffffff !important; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 16px; border: none; cursor: pointer; line-height: 1.5; mso-padding-alt: 0; text-align: center;">
                                                    <!--[if mso]>
                                                    <i style="letter-spacing: 25px; mso-font-width: -100%; mso-text-raise: 30pt;">&nbsp;</i>
                                                    <![endif]-->
                                                    <span style="color: #ffffff; text-decoration: none; mso-text-raise: 15pt;">Verify Email Address</span>
                                                    <!--[if mso]>
                                                    <i style="letter-spacing: 25px; mso-font-width: -100%;">&nbsp;</i>
                                                    <![endif]-->
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Note box -->
                                    <div style="background: #f8f9fa; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0;">
                                        <p style="margin: 0; color: #333333; font-size: 14px; line-height: 1.6;">
                                            <strong>⏰ This link will expire in 24 hours</strong><br>
                                            If you didn't create an account, you can safely ignore this email.
                                        </p>
                                    </div>

                                    <!-- Fallback link -->
                                    <p style="margin: 24px 0 0 0; color: #666666; font-size: 14px; line-height: 1.6;">
                                        If the button doesn't work, copy and paste this link into your browser:<br>
                                        <a href="{verification_url}" target="_blank" style="color: #667eea; word-break: break-all; text-decoration: underline;">{verification_url}</a>
                                    </p>
                                </td>
                            </tr>
                            <!-- Footer -->
                            <tr>
                                <td style="padding: 20px; text-align: center; background-color: #f5f5f5;">
                                    <p style="margin: 0; color: #666666; font-size: 14px;">© {app_name} · You're receiving this because you created an account</p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return EmailService.send_email(
            subject=subject, to_emails=[user_email], html_content=html_content
        )

    @staticmethod
    def send_welcome_email(user_email: str, username: str) -> bool:
        """
        Send simple welcome email to newly registered Django user (after verification).

        For Clerk users, Clerk sends its own welcome emails.
        """
        from django.conf import settings

        app_name = getattr(settings, "APP_NAME", "Crati.Co")

        subject = f"Welcome to {app_name}!"
        html_content = f"""
        <h2>Welcome, {username}!</h2>
        <p>Thank you for joining {app_name}.</p>
        <p><a href="{RegistrationEmailService.frontend_url}">Get Started</a></p>
        """

        return EmailService.send_email(
            subject=subject, to_emails=[user_email], html_content=html_content
        )


class NotificationEmailService:
    """Service for notification-related emails."""

    @staticmethod
    def send_notification_digest(
        user_email: str,
        username: str,
        notifications: List[Dict[str, Any]],
        digest_type: str = "daily",
        language: str = "en",
    ) -> bool:
        """
        Send notification digest email to user in their preferred language.

        Args:
            user_email: User's email address
            username: User's username
            notifications: List of notification data dictionaries
            digest_type: Type of digest ('daily', 'weekly', 'instant')
            language: User's preferred language ('en' or 'el')

        Returns:
            bool: True if sent successfully
        """
        context = {
            "username": username,
            "notifications": notifications,
            "digest_type": digest_type,
            "notification_count": len(notifications),
            "app_name": getattr(settings, "APP_NAME", "Diavgeia Platform"),
            "app_url": RegistrationEmailService.frontend_url,
        }

        # Localize subject based on language
        if language == "el":
            subject = f"Περίληψη Ειδοποιήσεων - {len(notifications)} νέα αποτελέσματα"
        else:
            subject = f"Your {digest_type.capitalize()} Notification Digest - {len(notifications)} new matches"

        return EmailService.send_template_email(
            subject=subject,
            to_emails=[user_email],
            template_name="emails/notifications/digest.html",
            context=context,
            language=language,
        )

    @staticmethod
    def send_notification_batch_summary(
        user_email: str, username: str, batch_data: Dict[str, Any], language: str = "en"
    ) -> bool:
        """
        Send summary email for a notification batch in user's preferred language.

        Args:
            user_email: User's email address
            username: User's username
            batch_data: Dictionary containing batch details
            language: User's preferred language ('en' or 'el')

        Returns:
            bool: True if sent successfully
        """
        context = {
            "username": username,
            "batch": batch_data,
            "app_name": getattr(settings, "APP_NAME", "Diavgeia Platform"),
            "app_url": RegistrationEmailService.frontend_url,
        }

        # Localize subject based on language
        if language == "el":
            subject = f"Νέες αποφάσεις που ταιριάζουν με τη συνδρομή σου: {batch_data.get('subscription_name', 'Χωρίς όνομα')}"
        else:
            subject = f"New decisions matched your subscription: {batch_data.get('subscription_name', 'Unnamed')}"

        return EmailService.send_template_email(
            subject=subject,
            to_emails=[user_email],
            template_name="emails/notifications/batch_summary.html",
            context=context,
            language=language,
        )


class PasswordResetEmailService:
    """
    Service for password reset emails (Django users only).

    Clerk users should use Clerk's built-in password reset flow.
    """

    frontend_url = (
        settings.FRONTEND_HOSTNAMES[0]
        if settings.FRONTEND_HOSTNAMES
        else "https://crati.co"
    )

    @staticmethod
    def send_password_reset_email(
        user_email: str, username: str, reset_token: str
    ) -> bool:
        """
        Send password reset link to user.

        Args:
            user_email: User's email address
            username: User's username
            reset_token: UUID token for password reset

        Returns:
            bool: True if sent successfully
        """
        from django.conf import settings

        app_name = getattr(settings, "APP_NAME", "Crati.Co")
        reset_url = f"{PasswordResetEmailService.frontend_url}/reset-password?token={reset_token}"

        subject = f"Reset your {app_name} password"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background: #ffffff; padding: 30px; border: 1px solid #e0e0e0; border-top: none; }}
                .button {{ display: inline-block; padding: 14px 32px; background: #667eea; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; margin: 20px 0; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 14px; }}
                .note {{ background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0; }}
                .warning {{ background: #f8d7da; padding: 15px; border-left: 4px solid #dc3545; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">🔒 Password Reset Request</h1>
                </div>
                <div class="content">
                    <h2>Hi {username},</h2>
                    <p>We received a request to reset your password for your {app_name} account.</p>

                    <p>Click the button below to set a new password:</p>

                    <div style="text-align: center;">
                        <a href="{reset_url}" class="button">Reset Password</a>
                    </div>

                    <div class="note">
                        <strong>⏰ This link will expire in 1 hour</strong><br>
                        For security reasons, password reset links are only valid for a short time.
                    </div>

                    <div class="warning">
                        <strong>⚠️ Did not request this?</strong><br>
                        If you didn't request a password reset, you can safely ignore this email.
                        Your password will remain unchanged.
                    </div>

                    <p style="color: #666; font-size: 14px; margin-top: 30px;">
                        If the button doesn't work, copy and paste this link into your browser:<br>
                        <a href="{reset_url}" style="color: #667eea; word-break: break-all;">{reset_url}</a>
                    </p>
                </div>
                <div class="footer">
                    <p>© {app_name} · Security notification</p>
                </div>
            </div>
        </body>
        </html>
        """

        return EmailService.send_email(
            subject=subject, to_emails=[user_email], html_content=html_content
        )

    @staticmethod
    def send_password_changed_notification(user_email: str, username: str) -> bool:
        """
        Send notification that password was successfully changed.

        Args:
            user_email: User's email address
            username: User's username

        Returns:
            bool: True if sent successfully
        """
        from django.conf import settings

        app_name = getattr(settings, "APP_NAME", "Crati.Co")

        subject = f"Your {app_name} password was changed"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background: #ffffff; padding: 30px; border: 1px solid #e0e0e0; border-top: none; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 14px; }}
                .info {{ background: #dcfce7; padding: 15px; border-left: 4px solid #10b981; margin: 20px 0; }}
                .warning {{ background: #f8d7da; padding: 15px; border-left: 4px solid #dc3545; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">✅ Password Changed</h1>
                </div>
                <div class="content">
                    <h2>Hi {username},</h2>

                    <div class="info">
                        <strong>Your password has been successfully changed.</strong><br>
                        You can now log in with your new password.
                    </div>

                    <div class="warning">
                        <strong>⚠️ Didn't make this change?</strong><br>
                        If you didn't change your password, please contact our support team immediately
                        as your account may be compromised.
                    </div>

                    <p>For your security, we recommend:</p>
                    <ul>
                        <li>Using a unique password for each service</li>
                        <li>Using a password manager</li>
                        <li>Changing your password periodically</li>
                    </ul>
                </div>
                <div class="footer">
                    <p>© {app_name} · Security notification</p>
                </div>
            </div>
        </body>
        </html>
        """

        return EmailService.send_email(
            subject=subject, to_emails=[user_email], html_content=html_content
        )
