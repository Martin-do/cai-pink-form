import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from returns.models import ReportingPeriod


class Command(BaseCommand):
    help = "Create the four quarterly reporting periods for a year."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=timezone.localdate().year)
        parser.add_argument("--days", type=int, default=settings.DEFAULT_DAYS_TO_SUBMIT,
                            help="Days after quarter end that the return is due.")

    def handle(self, year, days, **opts):
        for q in (1, 2, 3, 4):
            end_month = q * 3
            if end_month == 12:
                q_end = datetime.date(year, 12, 31)
            else:
                q_end = datetime.date(year, end_month + 1, 1) - datetime.timedelta(days=1)
            p, created = ReportingPeriod.objects.get_or_create(
                year=year, quarter=q,
                defaults={"due_date": q_end + datetime.timedelta(days=days)},
            )
            self.stdout.write(f"{'Created' if created else 'Exists '} {p.label} – due {p.due_date}")
