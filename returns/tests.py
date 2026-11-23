import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from directory.models import Assignment, Deanery, Parish, Priest
from returns import services
from returns.models import LineItem, QuarterlyReturn, ReportingPeriod

User = get_user_model()


class QuarterlyReturnWorkflowTests(TestCase):
    def setUp(self):
        call_command("load_pink_sheet")
        self.deanery = Deanery.objects.create(name="Oluyole", order=1)
        self.parish = Parish.objects.create(name="St. Kizito, Oluyole", deanery=self.deanery)
        self.priest_user = User.objects.create_user(username="priest@example.com", email="priest@example.com", password="pass12345")
        self.admin_user = User.objects.create_user(username="admin@example.com", email="admin@example.com", password="pass12345", is_staff=True)
        self.priest = Priest.objects.create(title="Fr.", full_name="Gregory Oyelami", user=self.priest_user)
        Assignment.objects.create(
            priest=self.priest, parish=self.parish,
            role=Assignment.ROLE_PARISH_PRIEST, start_date=datetime.date(2025, 1, 1),
        )
        self.q1 = ReportingPeriod.objects.create(
            year=2026, quarter=1, due_date=datetime.date(2026, 4, 30), levy_rate=Decimal("0.25"), is_open=True
        )
        self.q2 = ReportingPeriod.objects.create(
            year=2026, quarter=2, due_date=datetime.date(2026, 7, 30), levy_rate=Decimal("0.25"), is_open=True
        )

    def test_levy_calculation_submit_lock_unlock_waiver_and_export(self):
        cc_central = LineItem.objects.get(code="I02")     # levyable=True
        donations = LineItem.objects.get(code="I34")      # levyable=False
        maintenance = LineItem.objects.get(code="E02")    # expense

        ret = services.get_or_start_return(self.parish, self.q1, self.priest_user)
        services.save_entries(ret, {
            "opening_balance": "10000.00",
            "prepared_by": "Fr. Gregory",
            f"inc-{cc_central.id}-1-c": "100000.00",
            f"inc-{donations.id}-2-c": "40000.00",
            f"exp-{maintenance.id}-1-a": "30000.00",
        }, self.priest_user)

        ret.refresh_from_db()
        self.assertEqual(ret.total_income, Decimal("140000.00"))
        self.assertEqual(ret.total_expenditure, Decimal("30000.00"))
        self.assertEqual(ret.closing_balance, Decimal("120000.00"))
        # Only I02 (100,000) is levyable -> 25% = 25,000
        self.assertEqual(ret.levyable_income, Decimal("100000.00"))
        self.assertEqual(ret.levy_due, Decimal("25000.00"))

        # Submit & lock
        services.submit_return(ret, self.priest_user)
        ret.refresh_from_db()
        self.assertEqual(ret.status, QuarterlyReturn.STATUS_SUBMITTED)
        self.assertFalse(ret.is_editable)

        with self.assertRaises(services.ReturnLocked):
            services.save_entries(ret, {f"exp-{maintenance.id}-1-a": "999.00"}, self.priest_user)

        # Q2 carries forward Q1 closing balance (120,000)
        q2_ret = services.get_or_start_return(self.parish, self.q2, self.priest_user)
        self.assertTrue(q2_ret.opening_balance_carried)
        self.assertEqual(q2_ret.opening_balance, Decimal("120000.00"))

        # Waiver (partial 20% of 25,000 = 5,000 -> net 20,000)
        services.set_waiver(ret, self.admin_user, QuarterlyReturn.WAIVER_PERCENT, "20", "Roof repair relief")
        self.assertEqual(ret.waiver_amount, Decimal("5000.00"))
        self.assertEqual(ret.net_levy, Decimal("20000.00"))

        # Unlock by chancery
        services.unlock_return(ret, self.admin_user, "Missed March tithes")
        ret.refresh_from_db()
        self.assertEqual(ret.status, QuarterlyReturn.STATUS_UNLOCKED)
        self.assertTrue(ret.audit.filter(action="unlocked").exists())

        # Exports (PDF & Excel)
        self.client.force_login(self.priest_user)
        pdf_resp = self.client.get(reverse("return_pdf", args=[ret.pk]))
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertEqual(pdf_resp["Content-Type"], "application/pdf")

        xlsx_resp = self.client.get(reverse("return_xlsx", args=[ret.pk]))
        self.assertEqual(xlsx_resp.status_code, 200)

        self.client.force_login(self.admin_user)
        period_xlsx = self.client.get(reverse("period_xlsx", args=[self.q1.pk]))
        self.assertEqual(period_xlsx.status_code, 200)

    def test_chancery_and_priest_views_render(self):
        # Log in as Chancery admin using email and follow redirects to /chancery/
        resp = self.client.post(
            reverse("login"),
            {"username": "admin@example.com", "password": "pass12345"},
            follow=True,
        )
        self.assertRedirects(resp, reverse("chancery_dashboard"))
        self.assertEqual(resp.status_code, 200)

        for name in (
            "chancery_dashboard",
            "annual_summary",
            "period_list",
            "line_items",
            "signup_list",
            "priest_list",
            "parish_list",
            "transfer",
        ):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, f"Failed GET {name}")

        # Log in as linked priest and check priest portal views
        self.client.force_login(self.priest_user)
        self.assertEqual(self.client.get(reverse("my_dashboard")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("return_edit", args=[self.parish.pk, self.q1.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("parish_history", args=[self.parish.pk])).status_code,
            200,
        )
