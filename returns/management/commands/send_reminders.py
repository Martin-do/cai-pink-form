"""Email reminders for outstanding quarterly returns.

Run once a day (cron / Windows Task Scheduler / Railway cron):
    python manage.py send_reminders
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.template.loader import render_to_string
from django.utils import timezone

from directory.models import Assignment, Parish
from returns.models import QuarterlyReturn, ReminderLog, ReportingPeriod


def reminder_kind(period, today):
    delta = (period.due_date - today).days
    if delta in settings.REMINDER_DAYS_BEFORE:
        return f"before_{delta}"
    if delta == 0 and settings.REMINDER_ON_DUE_DATE:
        return "due_today"
    if delta < 0 and settings.REMINDER_OVERDUE_EVERY_DAYS and (-delta) % settings.REMINDER_OVERDUE_EVERY_DAYS == 0:
        return "overdue"
    return None


class Command(BaseCommand):
    help = "Send email reminders to parishes that have not submitted open-period returns."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Pretend today is YYYY-MM-DD (testing).")
        parser.add_argument("--force", action="store_true",
                            help="Send to all outstanding parishes regardless of schedule.")
        parser.add_argument("--no-digest", action="store_true")

    def handle(self, date=None, force=False, no_digest=False, **opts):
        import datetime
        today = datetime.date.fromisoformat(date) if date else timezone.localdate()
        sent = 0
        digest = []
        for period in ReportingPeriod.objects.filter(is_open=True):
            if today <= period.end_date and not force:
                continue  # quarter not finished yet
            kind = "manual" if force else reminder_kind(period, today)
            filed_ids = QuarterlyReturn.objects.filter(
                period=period, status__in=QuarterlyReturn.FILED_STATUSES
            ).values_list("parish_id", flat=True)
            outstanding = Parish.objects.filter(active=True, submits_returns=True).exclude(pk__in=filed_ids)
            if period.is_overdue:
                digest.append((period, list(outstanding)))
            if not kind:
                continue
            for parish in outstanding:
                emails = set()
                for a in parish.assignments.filter(Assignment.active_q()).select_related("priest__user"):
                    u = a.priest.user
                    if u and u.email and u.is_active:
                        emails.add(u.email)
                    elif a.priest.email:
                        emails.add(a.priest.email)
                if parish.email:
                    emails.add(parish.email)
                if not emails:
                    continue
                try:
                    ReminderLog.objects.create(parish=parish, period=period, kind=kind, sent_on=today,
                                               recipients=", ".join(sorted(emails)))
                except IntegrityError:
                    continue  # already sent today
                ctx = {"parish": parish, "period": period, "kind": kind, "today": today,
                       "days": (period.due_date - today).days, "site_url": settings.SITE_URL,
                       "diocese": settings.DIOCESE_NAME}
                send_mail(
                    subject=f"[{settings.DIOCESE_NAME}] Quarterly return {period} – "
                            + ("OVERDUE" if period.due_date < today else f"due {period.due_date:%d %b %Y}"),
                    message=render_to_string("emails/reminder.txt", ctx),
                    from_email=None, recipient_list=sorted(emails), fail_silently=True,
                )
                sent += 1

        # Weekly digest to chancery staff (Mondays) or when forced
        if digest and not no_digest and (today.weekday() == 0 or force):
            staff = list(get_user_model().objects.filter(is_staff=True, is_active=True)
                         .exclude(email="").values_list("email", flat=True))
            if staff:
                body = render_to_string("emails/digest.txt", {"digest": digest, "today": today,
                                                              "site_url": settings.SITE_URL})
                send_mail(f"[{settings.DIOCESE_NAME}] Outstanding quarterly returns", body,
                          None, staff, fail_silently=True)
        self.stdout.write(self.style.SUCCESS(f"Reminders sent: {sent}"))
