from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, call_command

from directory.models import Parish, Priest


class Command(BaseCommand):
    help = "Load the bundled initial dataset into an empty database once."

    def handle(self, *args, **options):
        if Parish.objects.exists():
            self.stdout.write("Initial parish data already exists; skipping fixture load.")
            return

        fixture = Path(settings.BASE_DIR) / "initial_data.json"
        if not fixture.is_file():
            self.stderr.write(self.style.ERROR(f"Initial data fixture not found: {fixture}"))
            return

        call_command("loaddata", str(fixture), verbosity=0)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded initial data: {Parish.objects.count()} parishes, "
                f"{Priest.objects.count()} priests."
            )
        )
