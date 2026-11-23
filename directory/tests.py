import datetime
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from directory.access import can_edit_parish, can_submit_for_parish, can_view_parish, current_parishes
from directory.models import AccountProfile, Assignment, Deanery, Parish, Priest

User = get_user_model()


class PriestAccessAndTransferTests(TestCase):
    def setUp(self):
        self.deanery = Deanery.objects.create(name="Oke Padi", order=1)
        self.parish_a = Parish.objects.create(name="St. Mary Cathedral", deanery=self.deanery)
        self.parish_b = Parish.objects.create(name="St. Jude, Iwo Road", deanery=self.deanery)
        self.priest = Priest.objects.create(title="Fr.", full_name="Julius Akinyode")
        self.user = User.objects.create_user(username="fr.julius@example.com", email="fr.julius@example.com", password="pass12345")
        self.admin = User.objects.create_user(username="chancery@example.com", email="chancery@example.com", password="pass12345", is_staff=True)

    def test_unlinked_user_has_no_parish_access(self):
        self.assertEqual(list(current_parishes(self.user)), [])
        self.assertFalse(can_view_parish(self.user, self.parish_a))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("my_dashboard"))
        self.assertRedirects(resp, reverse("pending"))

    def test_signup_and_chancery_approval_links_priest(self):
        resp = self.client.post(reverse("signup"), {
            "full_name": "Fr. Julius Akinyode",
            "email": "newpriest@example.com",
            "phone": "08012345678",
            "claimed_parish": self.parish_a.pk,
            "password1": "StrongPass!99",
            "password2": "StrongPass!99",
        }, follow=True)
        self.assertRedirects(resp, reverse("pending"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.wsgi_request.user.is_authenticated)
        profile = AccountProfile.objects.get(user__email="newpriest@example.com")
        self.assertEqual(profile.status, AccountProfile.STATUS_PENDING)

        self.client.force_login(self.admin)
        resp = self.client.post(reverse("signup_decide", args=[profile.pk]), {
            "action": "approve",
            f"p{profile.pk}-priest": self.priest.pk,
            f"p{profile.pk}-note": "Verified",
        })
        self.assertEqual(resp.status_code, 302)
        self.priest.refresh_from_db()
        self.assertEqual(self.priest.user, profile.user)

    def test_transfer_switches_parish_access_cleanly(self):
        today = timezone.localdate()
        self.priest.user = self.user
        self.priest.save()
        Assignment.objects.create(
            priest=self.priest, parish=self.parish_a,
            role=Assignment.ROLE_PARISH_PRIEST, start_date=today - datetime.timedelta(days=30),
        )
        self.assertEqual(list(current_parishes(self.user)), [self.parish_a])
        self.assertTrue(can_submit_for_parish(self.user, self.parish_a))
        self.assertFalse(can_view_parish(self.user, self.parish_b))

        # Chancery transfers priest to Parish B
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("transfer"), {
            "priest": self.priest.pk,
            "parish": self.parish_b.pk,
            "role": Assignment.ROLE_PARISH_PRIEST,
            "start_date": today.isoformat(),
            "end_current": "on",
            "end_incumbent": "on",
            "note": "Annual postings",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(list(current_parishes(self.user)), [self.parish_b])
        self.assertFalse(can_edit_parish(self.user, self.parish_a))
        self.assertTrue(can_submit_for_parish(self.user, self.parish_b))
