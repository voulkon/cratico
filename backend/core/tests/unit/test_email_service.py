"""
Tests for core.email_service — EmailService, NotificationEmailService,
RegistrationEmailService, and PasswordResetEmailService.

Uses Django's test email backend (locmem) which captures all outgoing
messages in ``django.core.mail.outbox`` without actually sending them.
"""

from unittest.mock import patch

import pytest
from django.conf import settings
from django.core import mail


# ── shared constants ──────────────────────────────────────────────────────

TEST_EMAIL = "test@example.com"
TEST_USERNAME = "testuser"


# =========================================================================
# EmailService.send_email
# =========================================================================


@pytest.mark.django_db
class TestEmailServiceSendEmail:
    """Tests for the low-level EmailService.send_email() static method."""

    def test_sends_basic_email(self):
        from core.email_service import EmailService

        result = EmailService.send_email(
            subject="Test Subject",
            to_emails=[TEST_EMAIL],
            html_content="<p>Hello <b>World</b></p>",
        )

        assert result is True
        assert len(mail.outbox) == 1

        sent = mail.outbox[0]
        assert sent.subject == "Test Subject"
        assert sent.to == [TEST_EMAIL]
        # Plain-text body should be auto-generated from HTML
        assert "Hello World" in sent.body
        # The HTML alternative should be attached
        html_alt = _get_html_alternative(sent)
        assert html_alt is not None
        assert "<b>World</b>" in html_alt

    def test_returns_false_and_logs_on_failure(self):
        from core.email_service import EmailService

        with patch("django.core.mail.EmailMultiAlternatives.send") as mock_send:
            mock_send.side_effect = ConnectionError("SMTP down")

            result = EmailService.send_email(
                subject="Will Fail",
                to_emails=[TEST_EMAIL],
                html_content="<p>content</p>",
            )

        assert result is False

    def test_empty_recipients_returns_false(self):
        from core.email_service import EmailService

        result = EmailService.send_email(
            subject="No One", to_emails=[], html_content="<p>who cares</p>"
        )

        assert result is False
        assert len(mail.outbox) == 0

    def test_custom_from_email_is_used(self):
        from core.email_service import EmailService

        EmailService.send_email(
            subject="Custom From",
            to_emails=[TEST_EMAIL],
            html_content="<p>x</p>",
            from_email="custom@from.com",
        )

        assert mail.outbox[0].from_email == "custom@from.com"

    def test_default_from_email_fallback(self):
        from core.email_service import EmailService

        EmailService.send_email(
            subject="Default From",
            to_emails=[TEST_EMAIL],
            html_content="<p>x</p>",
        )

        assert mail.outbox[0].from_email == settings.DEFAULT_FROM_EMAIL

    def test_cc_bcc_reply_to_forwarded(self):
        from core.email_service import EmailService

        EmailService.send_email(
            subject="CC/BCC Test",
            to_emails=[TEST_EMAIL],
            html_content="<p>x</p>",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            reply_to=["reply@example.com"],
        )

        sent = mail.outbox[0]
        assert sent.cc == ["cc@example.com"]
        assert sent.bcc == ["bcc@example.com"]
        assert sent.reply_to == ["reply@example.com"]

    def test_attachments_are_included(self):
        from core.email_service import EmailService

        EmailService.send_email(
            subject="With Attachment",
            to_emails=[TEST_EMAIL],
            html_content="<p>x</p>",
            attachments=[("report.csv", b"col1,col2", "text/csv")],
        )

        sent = mail.outbox[0]
        # After sending, attachments become MIMEBase objects; just verify count
        assert len(sent.attachments) == 1

    def test_explicit_text_content_bypasses_auto_generation(self):
        from core.email_service import EmailService

        EmailService.send_email(
            subject="Explicit Text",
            to_emails=[TEST_EMAIL],
            html_content="<p>HTML version</p>",
            text_content="Plain text version",
        )

        assert mail.outbox[0].body == "Plain text version"


# =========================================================================
# EmailService.send_template_email
# =========================================================================


@pytest.mark.django_db
class TestEmailServiceSendTemplateEmail:
    """Tests for template-based email sending."""

    def test_renders_and_sends_template(self):
        from core.email_service import EmailService

        result = EmailService.send_template_email(
            subject="Template Test",
            to_emails=[TEST_EMAIL],
            template_name="emails/notifications/digest.en.html",
            context={
                "username": TEST_USERNAME,
                "notifications": [],
                "digest_type": "daily",
                "notification_count": 0,
                "app_name": "TestApp",
                "app_url": "https://example.com",
            },
        )

        assert result is True
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == "Template Test"

    def test_language_already_in_template_name_skips_language_logic(self):
        """When the template already ends with '.en.html', the language
        parameter is effectively ignored (no suffix injection)."""
        from core.email_service import EmailService

        result = EmailService.send_template_email(
            subject="Lang Already Present",
            to_emails=[TEST_EMAIL],
            template_name="emails/notifications/digest.en.html",
            context={
                "username": TEST_USERNAME,
                "notifications": [],
                "digest_type": "daily",
                "notification_count": 0,
                "app_name": "TestApp",
                "app_url": "https://example.com",
            },
            language="el",  # ignored because template already has .en.html
        )

        assert result is True
        assert len(mail.outbox) == 1
        # Still renders the English template (check for content from the en template)
        html_alt = _get_html_alternative(mail.outbox[0])
        assert "New Notification" in html_alt


# =========================================================================
# NotificationEmailService
# =========================================================================


@pytest.mark.django_db
class TestNotificationEmailService:
    """Tests for notification-related email sending."""

    def test_send_notification_digest_english(self):
        from core.email_service import NotificationEmailService

        notifications = [
            {"subject": "Decision A", "organization": "Org A", "date": "2026-06-10"},
        ]

        result = NotificationEmailService.send_notification_digest(
            user_email=TEST_EMAIL,
            username=TEST_USERNAME,
            notifications=notifications,
            digest_type="daily",
            language="en",
        )

        assert result is True
        sent = mail.outbox[0]
        assert "1 new match" in sent.subject

    def test_send_notification_digest_greek(self):
        from core.email_service import NotificationEmailService

        result = NotificationEmailService.send_notification_digest(
            user_email=TEST_EMAIL,
            username=TEST_USERNAME,
            notifications=[{"subject": "Απόφαση", "organization": "Οργ", "date": "2026-06-10"}],
            digest_type="daily",
            language="el",
        )

        assert result is True
        sent = mail.outbox[0]
        # Greek subject should be used
        assert "Περίληψη Ειδοποιήσεων" in sent.subject

    def test_send_notification_batch_summary_english(self):
        from core.email_service import NotificationEmailService

        batch_data = {
            "id": 1,
            "subscription_name": "My Sub",
            "organization_name": "Ministry of Finance",
            "entity_name": None,
            "decision_count": 3,
            "check_window_start": "2026-06-09",
            "check_window_end": "2026-06-10",
            "decisions": [
                {"id": "ADA1", "subject": "Decision 1", "organization": "Org1", "date": "2026-06-10"},
                {"id": "ADA2", "subject": "Decision 2", "organization": "Org2", "date": "2026-06-10"},
            ],
            "app_url": "https://crati.co",
        }

        result = NotificationEmailService.send_notification_batch_summary(
            user_email=TEST_EMAIL,
            username=TEST_USERNAME,
            batch_data=batch_data,
            language="en",
        )

        assert result is True
        assert len(mail.outbox) == 1
        assert "My Sub" in mail.outbox[0].subject

    def test_send_notification_batch_summary_greek(self):
        from core.email_service import NotificationEmailService

        batch_data = {
            "id": 1,
            "subscription_name": "Η Συνδρομή Μου",
            "organization_name": "Υπουργείο",
            "entity_name": None,
            "decision_count": 5,
            "check_window_start": "2026-06-09",
            "check_window_end": "2026-06-10",
            "decisions": [],
            "app_url": "https://crati.co",
        }

        result = NotificationEmailService.send_notification_batch_summary(
            user_email=TEST_EMAIL,
            username=TEST_USERNAME,
            batch_data=batch_data,
            language="el",
        )

        assert result is True
        assert "ταιριάζουν" in mail.outbox[0].subject


# =========================================================================
# RegistrationEmailService
# =========================================================================


@pytest.mark.django_db
class TestRegistrationEmailService:
    """Tests for registration-related emails."""

    def test_send_verification_email(self):
        from core.email_service import RegistrationEmailService

        result = RegistrationEmailService.send_verification_email(
            user_email=TEST_EMAIL,
            username=TEST_USERNAME,
            verification_token="abc123-token",
        )

        assert result is True
        sent = mail.outbox[0]
        assert "Verify your" in sent.subject
        assert TEST_USERNAME in _get_html_alternative(sent)
        assert "abc123-token" in _get_html_alternative(sent)

    def test_send_welcome_email(self):
        from core.email_service import RegistrationEmailService

        result = RegistrationEmailService.send_welcome_email(
            user_email=TEST_EMAIL, username=TEST_USERNAME
        )

        assert result is True
        sent = mail.outbox[0]
        assert "Welcome" in sent.subject
        assert TEST_USERNAME in _get_html_alternative(sent)


# =========================================================================
# PasswordResetEmailService
# =========================================================================


@pytest.mark.django_db
class TestPasswordResetEmailService:
    """Tests for password-reset emails."""

    def test_send_password_reset_email(self):
        from core.email_service import PasswordResetEmailService

        result = PasswordResetEmailService.send_password_reset_email(
            user_email=TEST_EMAIL,
            username=TEST_USERNAME,
            reset_token="reset-token-456",
        )

        assert result is True
        sent = mail.outbox[0]
        assert "Reset your" in sent.subject
        html = _get_html_alternative(sent)
        assert "reset-token-456" in html

    def test_send_password_changed_notification(self):
        from core.email_service import PasswordResetEmailService

        result = PasswordResetEmailService.send_password_changed_notification(
            user_email=TEST_EMAIL, username=TEST_USERNAME
        )

        assert result is True
        sent = mail.outbox[0]
        assert "password was changed" in sent.subject
        html = _get_html_alternative(sent)
        assert TEST_USERNAME in html


# =========================================================================
# Consolidated email — AI one-liner bullets
# =========================================================================


def _consolidated_batch(batches):
    """Call the consolidated email service with the given batch data."""
    from core.email_service import NotificationEmailService

    total = sum(b.get("decision_count", 0) for b in batches)
    result = NotificationEmailService.send_consolidated_batch_summary(
        user_email=TEST_EMAIL,
        username=TEST_USERNAME,
        batches=batches,
        total_decisions=total,
        language="en",
    )
    assert result is True
    sent = mail.outbox[-1]
    return _get_html_alternative(sent)


@pytest.mark.django_db
class TestConsolidatedEmailSummaryBullets:
    """AI one-liner bullets + decision links in the consolidated email."""

    def test_renders_bullets_with_decision_links_when_items_present(self):
        batches = [
            {
                "id": 5,
                "subscription_name": "My Sub",
                "organization_name": None,
                "entity_name": None,
                "decision_count": 2,
                "ai_summary_status": "COMPLETED",
                "ai_summary_items": [
                    {
                        "decision_id": 101,
                        "ada": "ΑΒΓΔΕ-ΖΗΘ",
                        "subject": "Approval of works",
                        "one_liner": "Εγκρίθηκε δαπάνη 1.000 ευρώ.",
                    },
                    {
                        "decision_id": 102,
                        "ada": "ΑΒΓΔΕ-ΖΙΚ",
                        "subject": "",
                        "one_liner": "Ανακήρυξη αναδόχου.",
                    },
                ],
            }
        ]

        html = _consolidated_batch(batches)

        # One bullet per item, linked to the decision page
        assert html.count("/decision/101") == 1
        assert html.count("/decision/102") == 1
        # Link text: subject, falling back to ada when the subject is empty
        assert "Approval of works" in html
        assert "ΑΒΓΔΕ-ΖΙΚ" in html
        # The one-liner is rendered next to the link
        assert "Εγκρίθηκε δαπάνη 1.000 ευρώ." in html
        assert "Ανακήρυξη αναδόχου." in html

    def test_falls_back_to_plain_rendering_without_items(self):
        """AI disabled/failed → no bullets, classic batch block only."""
        batches = [
            {
                "id": 5,
                "subscription_name": "My Sub",
                "organization_name": None,
                "entity_name": None,
                "decision_count": 1,
                "ai_summary_status": "SKIPPED",
                "ai_summary_items": [],
            }
        ]

        html = _consolidated_batch(batches)

        assert "/decision/" not in html
        assert "/batch/5" in html
        assert "View Matches" in html

    def test_greek_template_renders_bullets(self):
        batches = [
            {
                "id": 9,
                "subscription_name": "Η συνδρομή μου",
                "organization_name": None,
                "entity_name": None,
                "decision_count": 1,
                "ai_summary_status": "COMPLETED",
                "ai_summary_items": [
                    {
                        "decision_id": 7,
                        "ada": "ΑΒΓΔΕ-ΩΚΦ",
                        "subject": "Ανάθεση έργου",
                        "one_liner": "Υπογράφηκε σύμβαση.",
                    }
                ],
            }
        ]

        from core.email_service import NotificationEmailService

        result = NotificationEmailService.send_consolidated_batch_summary(
            user_email=TEST_EMAIL,
            username=TEST_USERNAME,
            batches=batches,
            total_decisions=1,
            language="el",
        )

        assert result is True
        html = _get_html_alternative(mail.outbox[-1])
        assert "/decision/7" in html
        assert "Υπογράφηκε σύμβαση." in html


# =========================================================================
# helpers
# =========================================================================


def _get_html_alternative(msg):
    """Extract the HTML alternative body from an EmailMultiAlternatives message."""
    for content, mime_type in msg.alternatives:
        if mime_type == "text/html":
            return content
    return None
