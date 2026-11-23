from django.contrib import admin

from .models import (
    AuditLog,
    ExpenseEntry,
    IncomeEntry,
    LevyPayment,
    LineItem,
    QuarterlyReturn,
    ReminderLog,
    ReportingPeriod,
)


@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ("code", "kind", "group", "label", "order", "is_levyable", "needs_detail", "active")
    list_filter = ("kind", "is_levyable", "active", "group")
    search_fields = ("code", "label", "group")
    list_editable = ("is_levyable", "active")


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ("year", "quarter", "due_date", "levy_rate", "is_open")
    list_filter = ("year", "is_open")


class IncomeInline(admin.TabularInline):
    model = IncomeEntry
    extra = 0


class ExpenseInline(admin.TabularInline):
    model = ExpenseEntry
    extra = 0


@admin.register(QuarterlyReturn)
class QuarterlyReturnAdmin(admin.ModelAdmin):
    list_display = (
        "parish", "period", "status", "total_income", "total_expenditure",
        "closing_balance", "levy_due", "waiver_type", "submitted_at",
    )
    list_filter = ("period", "status", "waiver_type", "parish__deanery")
    search_fields = ("parish__name",)
    readonly_fields = ("submitted_at", "submitted_by", "accepted_at", "accepted_by")
    inlines = [IncomeInline, ExpenseInline]


@admin.register(LevyPayment)
class LevyPaymentAdmin(admin.ModelAdmin):
    list_display = ("ret", "amount", "date_paid", "method", "reference", "recorded_by")
    list_filter = ("method", "date_paid")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "ret", "actor", "detail")
    list_filter = ("action",)
    readonly_fields = ("ret", "actor", "action", "detail", "created_at")


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = ("sent_on", "period", "parish", "kind")
    list_filter = ("period", "kind", "sent_on")
