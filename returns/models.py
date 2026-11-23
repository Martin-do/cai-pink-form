import datetime
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from directory.models import Parish

MONEY = dict(max_digits=16, decimal_places=2, default=Decimal("0.00"))
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class LineItem(models.Model):
    """One row of the pink sheet. Editable by the chancery (data, not code)."""

    KIND_INCOME = "income"
    KIND_EXPENSE = "expense"
    KIND_CHOICES = [(KIND_INCOME, "Income"), (KIND_EXPENSE, "Expenditure")]

    code = models.CharField(max_length=10, unique=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    group = models.CharField(max_length=80)
    label = models.CharField(max_length=150)
    order = models.PositiveIntegerField(default=0)
    is_levyable = models.BooleanField(
        default=False, help_text="Counts towards income subject to Cathedraticum."
    )
    needs_detail = models.BooleanField(default=False, help_text="Shows a 'specify' note box.")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "order"]

    def __str__(self):
        return f"{self.code} {self.group}: {self.label}"

    @property
    def full_label(self):
        if self.label.lower().startswith(self.group.lower()) or self.label == self.group:
            return self.label
        return f"{self.group}: {self.label}"


class ReportingPeriod(models.Model):
    year = models.PositiveIntegerField()
    quarter = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    due_date = models.DateField()
    levy_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal(settings.DEFAULT_LEVY_RATE),
        help_text="Cathedraticum rate as a fraction, e.g. 0.25 for 25%.",
    )
    is_open = models.BooleanField(
        default=True, help_text="Parishes can create and submit returns for open periods."
    )

    class Meta:
        ordering = ["-year", "-quarter"]
        unique_together = [("year", "quarter")]

    def __str__(self):
        return f"Q{self.quarter} {self.year}"

    @property
    def month_numbers(self):
        start = (self.quarter - 1) * 3 + 1
        return [start, start + 1, start + 2]

    @property
    def month_names(self):
        return [MONTH_NAMES[m - 1] for m in self.month_numbers]

    @property
    def label(self):
        n = self.month_names
        return f"Q{self.quarter} {self.year} ({n[0][:3]}–{n[2][:3]})"

    @property
    def start_date(self):
        return datetime.date(self.year, self.month_numbers[0], 1)

    @property
    def end_date(self):
        m = self.month_numbers[2]
        if m == 12:
            return datetime.date(self.year, 12, 31)
        return datetime.date(self.year, m + 1, 1) - datetime.timedelta(days=1)

    @property
    def is_overdue(self):
        return timezone.localdate() > self.due_date

    def previous(self):
        y, q = (self.year, self.quarter - 1) if self.quarter > 1 else (self.year - 1, 4)
        return ReportingPeriod.objects.filter(year=y, quarter=q).first()

    @property
    def levy_percent(self):
        return (self.levy_rate * 100).normalize()


class QuarterlyReturn(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_UNLOCKED = "unlocked"
    STATUS_ACCEPTED = "accepted"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_UNLOCKED, "Returned for correction"),
        (STATUS_ACCEPTED, "Accepted"),
    ]
    EDITABLE_STATUSES = (STATUS_DRAFT, STATUS_UNLOCKED)
    FILED_STATUSES = (STATUS_SUBMITTED, STATUS_ACCEPTED)

    WAIVER_NONE = "none"
    WAIVER_FULL = "full"
    WAIVER_AMOUNT = "amount"
    WAIVER_PERCENT = "percent"
    WAIVER_CHOICES = [
        (WAIVER_NONE, "No waiver"),
        (WAIVER_FULL, "Full waiver"),
        (WAIVER_AMOUNT, "Partial – fixed amount"),
        (WAIVER_PERCENT, "Partial – percentage of levy"),
    ]

    parish = models.ForeignKey(Parish, on_delete=models.PROTECT, related_name="returns")
    period = models.ForeignKey(ReportingPeriod, on_delete=models.PROTECT, related_name="returns")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    opening_balance = models.DecimalField(**MONEY)
    opening_balance_carried = models.BooleanField(
        default=False, help_text="Opening balance carried forward from the previous quarter."
    )
    prepared_by = models.CharField(max_length=150, blank=True)
    remarks = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Snapshot of totals (refreshed on every save/submit) for fast dashboards
    total_income = models.DecimalField(**MONEY)
    total_expenditure = models.DecimalField(**MONEY)
    closing_balance = models.DecimalField(**MONEY)
    levyable_income = models.DecimalField(**MONEY)
    levy_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0"))
    levy_due = models.DecimalField(**MONEY)

    # Waiver (chancery only)
    waiver_type = models.CharField(max_length=10, choices=WAIVER_CHOICES, default=WAIVER_NONE)
    waiver_value = models.DecimalField(**MONEY)
    waiver_reason = models.CharField(max_length=255, blank=True)
    waived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    waived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period__year", "-period__quarter", "parish__name"]
        constraints = [
            models.UniqueConstraint(fields=["parish", "period"], name="one_return_per_parish_period")
        ]

    def __str__(self):
        return f"{self.parish} – {self.period}"

    # ---- state helpers ----
    @property
    def is_editable(self):
        return self.status in self.EDITABLE_STATUSES

    @property
    def is_filed(self):
        return self.status in self.FILED_STATUSES

    @property
    def is_late(self):
        if self.submitted_at:
            return self.submitted_at.date() > self.period.due_date
        return self.period.is_overdue

    # ---- levy ----
    @property
    def waiver_amount(self):
        due = self.levy_due
        if self.waiver_type == self.WAIVER_FULL:
            return due
        if self.waiver_type == self.WAIVER_AMOUNT:
            return min(self.waiver_value, due)
        if self.waiver_type == self.WAIVER_PERCENT:
            pct = min(max(self.waiver_value, Decimal(0)), Decimal(100))
            return (due * pct / Decimal(100)).quantize(Decimal("0.01"))
        return Decimal("0.00")

    @property
    def net_levy(self):
        return self.levy_due - self.waiver_amount

    @property
    def amount_paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal("0.00"))

    @property
    def levy_outstanding(self):
        return self.net_levy - self.amount_paid

    @property
    def surplus(self):
        return self.total_income - self.total_expenditure


class IncomeEntry(models.Model):
    ret = models.ForeignKey(QuarterlyReturn, on_delete=models.CASCADE, related_name="income_entries")
    line = models.ForeignKey(LineItem, on_delete=models.PROTECT, limit_choices_to={"kind": "income"})
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(3)])
    central = models.DecimalField(**MONEY)
    outstation = models.DecimalField(**MONEY)
    other = models.DecimalField(**MONEY)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("ret", "line", "month")]

    @property
    def total(self):
        return self.central + self.outstation + self.other


class ExpenseEntry(models.Model):
    ret = models.ForeignKey(QuarterlyReturn, on_delete=models.CASCADE, related_name="expense_entries")
    line = models.ForeignKey(LineItem, on_delete=models.PROTECT, limit_choices_to={"kind": "expense"})
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(3)])
    amount = models.DecimalField(**MONEY)
    note = models.CharField(max_length=255, blank=True, help_text="Payee / details / voucher ref.")

    class Meta:
        unique_together = [("ret", "line", "month")]


class LevyPayment(models.Model):
    METHOD_CHOICES = [
        ("transfer", "Bank transfer"),
        ("deposit", "Bank deposit"),
        ("cash", "Cash"),
        ("cheque", "Cheque"),
        ("other", "Other"),
    ]
    ret = models.ForeignKey(QuarterlyReturn, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=16, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    date_paid = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default="transfer")
    reference = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_paid"]


class AuditLog(models.Model):
    ret = models.ForeignKey(
        QuarterlyReturn, null=True, blank=True, on_delete=models.CASCADE, related_name="audit"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=40)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class ReminderLog(models.Model):
    parish = models.ForeignKey(Parish, on_delete=models.CASCADE, related_name="reminders")
    period = models.ForeignKey(ReportingPeriod, on_delete=models.CASCADE, related_name="reminders")
    kind = models.CharField(max_length=30)
    sent_on = models.DateField(default=timezone.localdate)
    recipients = models.TextField(blank=True)

    class Meta:
        ordering = ["-sent_on"]
        unique_together = [("parish", "period", "kind", "sent_on")]
