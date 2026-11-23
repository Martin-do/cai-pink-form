from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Deanery(models.Model):
    name = models.CharField(max_length=120, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "deaneries"

    def __str__(self):
        return self.name


class Parish(models.Model):
    KIND_PARISH = "parish"
    KIND_CHAPLAINCY = "chaplaincy"
    KIND_INSTITUTION = "institution"
    KIND_CHOICES = [
        (KIND_PARISH, "Parish"),
        (KIND_CHAPLAINCY, "Chaplaincy"),
        (KIND_INSTITUTION, "Institution / School"),
    ]

    name = models.CharField(max_length=200, unique=True)
    deanery = models.ForeignKey(Deanery, on_delete=models.PROTECT, related_name="parishes")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_PARISH)
    run_by_religious = models.BooleanField(
        default=False, help_text="Parish run by a religious congregation."
    )
    religious_congregation = models.CharField(max_length=60, blank=True)
    submits_returns = models.BooleanField(
        default=True, help_text="Untick if this unit is not required to file quarterly returns."
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["deanery__order", "name"]
        verbose_name_plural = "parishes"

    def __str__(self):
        return self.name

    def current_assignments(self):
        return self.assignments.filter(Assignment.active_q()).select_related("priest")

    def parish_priest(self):
        a = self.current_assignments().filter(role__in=Assignment.HEAD_ROLES).first()
        return a.priest if a else None


class Priest(models.Model):
    title = models.CharField(max_length=20, default="Fr.", help_text="Fr., Msgr., Rev., etc.")
    full_name = models.CharField(max_length=150)
    congregation = models.CharField(
        max_length=30, blank=True, help_text="Religious congregation suffix, e.g. SMA, OP, CSsR."
    )
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="priest",
        help_text="Portal account linked to this priest (set by the chancery).",
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        s = f"{self.title} {self.full_name}".strip()
        return f"{s}, {self.congregation}" if self.congregation else s

    def current_assignments(self):
        return self.assignments.filter(Assignment.active_q()).select_related("parish")


class Assignment(models.Model):
    """Links a priest to a parish for a period of time.

    Access to a parish's returns is granted ONLY through an active assignment,
    so transferring a priest = ending one assignment and starting another.
    """

    ROLE_PARISH_PRIEST = "pp"
    ROLE_ADMINISTRATOR = "admin"
    ROLE_ASSISTANT = "asst"
    ROLE_CHOICES = [
        (ROLE_PARISH_PRIEST, "Parish Priest"),
        (ROLE_ADMINISTRATOR, "Parish Administrator / Chaplain"),
        (ROLE_ASSISTANT, "Assistant Priest"),
    ]
    HEAD_ROLES = (ROLE_PARISH_PRIEST, ROLE_ADMINISTRATOR)

    priest = models.ForeignKey(Priest, on_delete=models.CASCADE, related_name="assignments")
    parish = models.ForeignKey(Parish, on_delete=models.CASCADE, related_name="assignments")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_PARISH_PRIEST)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.priest} – {self.get_role_display()} – {self.parish}"

    @staticmethod
    def active_q(on=None):
        on = on or timezone.localdate()
        return Q(start_date__lte=on) & (Q(end_date__isnull=True) | Q(end_date__gte=on))

    @property
    def is_active(self):
        today = timezone.localdate()
        return self.start_date <= today and (self.end_date is None or self.end_date >= today)

    @property
    def can_submit(self):
        return self.role in self.HEAD_ROLES


class AccountProfile(models.Model):
    """Extra sign-up info and approval state for portal users."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending approval"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    phone = models.CharField(max_length=30, blank=True)
    name_as_listed = models.CharField(
        max_length=150, help_text="Name as it appears on the Archdiocesan priests list."
    )
    claimed_parish = models.ForeignKey(
        Parish, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="Parish the applicant says they currently head (information only).",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_username()} ({self.get_status_display()})"
