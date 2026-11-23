from django.contrib import admin

from .models import AccountProfile, Assignment, Deanery, Parish, Priest


@admin.register(Deanery)
class DeaneryAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    ordering = ("order", "name")


@admin.register(Parish)
class ParishAdmin(admin.ModelAdmin):
    list_display = ("name", "deanery", "kind", "run_by_religious", "submits_returns", "active")
    list_filter = ("deanery", "kind", "run_by_religious", "submits_returns", "active")
    search_fields = ("name",)


@admin.register(Priest)
class PriestAdmin(admin.ModelAdmin):
    list_display = ("title", "full_name", "congregation", "user", "active")
    list_filter = ("active", "congregation")
    search_fields = ("full_name", "email", "phone")
    raw_id_fields = ("user",)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("priest", "parish", "role", "start_date", "end_date")
    list_filter = ("role", "parish__deanery")
    search_fields = ("priest__full_name", "parish__name")
    date_hierarchy = "start_date"


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "name_as_listed", "claimed_parish", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name_as_listed", "user__email", "phone")
