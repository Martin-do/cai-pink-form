from django.core.management.base import BaseCommand

from returns.models import LineItem
from returns.pink_sheet import EXPENSE_LINES, INCOME_LINES


class Command(BaseCommand):
    help = "Create/update pink sheet line items (income & expenditure headings)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-flags", action="store_true",
            help="Also overwrite is_levyable/needs_detail on existing lines.",
        )

    def handle(self, *args, reset_flags=False, **opts):
        created = updated = 0
        for kind, rows in ((LineItem.KIND_INCOME, INCOME_LINES), (LineItem.KIND_EXPENSE, EXPENSE_LINES)):
            for order, (code, group, label, levyable, detail) in enumerate(rows, start=1):
                obj, was_created = LineItem.objects.get_or_create(
                    code=code,
                    defaults=dict(kind=kind, group=group, label=label, order=order,
                                  is_levyable=levyable, needs_detail=detail),
                )
                if was_created:
                    created += 1
                    continue
                obj.kind, obj.group, obj.label, obj.order = kind, group, label, order
                if reset_flags:
                    obj.is_levyable, obj.needs_detail = levyable, detail
                obj.save()
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"Line items: {created} created, {updated} updated."))
