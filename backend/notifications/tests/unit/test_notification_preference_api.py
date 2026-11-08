"""API tests for the user-level notification preference endpoint (§6.6)."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def disable_stealth_mode():
    """The stealth middleware returns 401 before DRF sees force_authenticate."""
    from unittest.mock import patch

    with patch(
        "core.services.feature_flag_service.feature_flags.is_enabled",
        return_value=False,
    ):
        yield


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class TestNotificationPreferenceApi:
    def test_user_reads_only_their_own_preference(self, user):
        from conftest import UserFactory

        other = UserFactory()
        response = _client(user).get(reverse("notification-preference-list"))

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == user.notification_preference.id
        assert other.notification_preference.id != user.notification_preference.id

    def test_user_updates_their_own_preference(self, user):
        preference = user.notification_preference
        url = reverse("notification-preference-detail", args=[preference.id])

        response = _client(user).patch(
            url,
            {
                "email_mode": "daily_digest",
                "digest_hours_local": [13, 10, 13],
            },
            format="json",
        )

        assert response.status_code == 200
        preference.refresh_from_db()
        assert preference.email_mode == "daily_digest"
        assert preference.digest_hours_local == [10, 13]
        assert preference.digest_hour_local == 10

    def test_legacy_digest_hour_updates_the_list(self, user):
        preference = user.notification_preference
        url = reverse("notification-preference-detail", args=[preference.id])

        response = _client(user).patch(
            url,
            {"digest_hour_local": 19},
            format="json",
        )

        assert response.status_code == 200
        preference.refresh_from_db()
        assert preference.digest_hour_local == 19
        assert preference.digest_hours_local == [19]

    def test_other_users_preference_is_not_found(self, user):
        from conftest import UserFactory

        other = UserFactory()
        url = reverse(
            "notification-preference-detail",
            args=[other.notification_preference.id],
        )

        response = _client(user).get(url)

        assert response.status_code == 404

    def test_list_and_detail_use_a_constant_number_of_queries(
        self, user, django_assert_num_queries
    ):
        preference = user.notification_preference
        list_url = reverse("notification-preference-list")
        detail_url = reverse("notification-preference-detail", args=[preference.id])
        client = _client(user)

        with django_assert_num_queries(1):
            assert client.get(list_url).status_code == 200

        with django_assert_num_queries(1):
            assert client.get(detail_url).status_code == 200
