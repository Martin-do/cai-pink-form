"""Import deaneries, parishes, priests and current assignments from the
'PRIESTS IN PARISHES PER DEANERY' Word document (or a CSV)."""
import csv
import datetime
import re

import docx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from directory.models import Assignment, Deanery, Parish, Priest

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
RELIGIOUS_FILL = "00B0F0"
TITLES = ["Msgr.", "Msgr", "Fr.", "Fr", "Rev.", "Rev", "Col.", "Col", "Very Rev.", "Bishop"]
SECTION_KINDS = {
    "CHAPLAINCY": Parish.KIND_CHAPLAINCY,
    "INSTITUTIONS AND SCHOOLS": Parish.KIND_INSTITUTION,
}


def clean_parish(name):
    name = re.sub(r"^\s*\d+\.\s*", "", name).strip()
    name = re.sub(r",(?=\S)", ", ", name)          # "Church,Iwo" -> "Church, Iwo"
    name = re.sub(r"\bSt\.(?=\S)", "St. ", name)    # "St.Anne" -> "St. Anne"
    name = re.sub(r"\s+", " ", name).strip().rstrip(".").strip()
    return name


def split_priest(raw):
    raw = re.sub(r"\s+", " ", raw).strip().rstrip(".").strip()
    if not raw:
        return None
    congregation = ""
    if "," in raw:
        raw, congregation = [p.strip() for p in raw.split(",", 1)]
    title = "Fr."
    for t in TITLES:
        if raw.startswith(t + " "):
            title = t if t.endswith(".") else t + "."
            raw = raw[len(t):].strip()
            break
    return title, raw.strip(), congregation


def cell_fill(cell):
    tcPr = cell._tc.tcPr
    if tcPr is None:
        return ""
    shd = tcPr.find(W + "shd")
    return (shd.get(W + "fill") or "") if shd is not None else ""


def parse_docx(path):
    """Yield dicts: deanery, kind, parish, religious, congregation, priests[list]."""
    d = docx.Document(path)
    records = []
    deanery, kind = None, Parish.KIND_PARISH
    for table in d.tables:
        for row in table.rows:
            cells = row.cells
            if len(cells) < 3:
                continue
            name = cells[1].text.strip()
            priests_raw = cells[-1].text.strip()
            if name.upper().startswith("DEANERY/PARISH") or name.lower().startswith("parishes run by"):
                continue
            fill = cell_fill(cells[1]).upper()
            if name and not priests_raw and name == name.upper() and len(name) < 40 \
                    and not re.search(r"\d", name):
                deanery = name.title()
                kind = SECTION_KINDS.get(name.upper(), Parish.KIND_PARISH)
                continue
            priest_names = [p for p in (x.strip() for x in priests_raw.split("\n")) if p]
            if name:
                cong = ""
                m = re.search(r"\(([^)]+)\)", name)
                if m:
                    cong = m.group(1)
                records.append({
                    "deanery": deanery, "kind": kind, "parish": clean_parish(name),
                    "religious": fill == RELIGIOUS_FILL, "congregation": cong,
                    "priests": priest_names,
                })
            elif priest_names and records:
                records[-1]["priests"].extend(priest_names)
    return records


def parse_csv(path):
    """CSV columns: deanery, parish, kind(optional), priest, role(optional)."""
    by_parish = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            p = clean_parish(row["parish"])
            rec = by_parish.setdefault(p, {
                "deanery": row["deanery"].strip(), "kind": (row.get("kind") or "parish").strip(),
                "parish": p, "religious": False, "congregation": "", "priests": [],
            })
            if row.get("priest"):
                rec["priests"].append(row["priest"].strip())
    return list(by_parish.values())


class Command(BaseCommand):
    help = "Import deaneries, parishes, priests and assignments from the priests list (.docx or .csv)."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--start-date", default="2026-08-26",
                            help="Start date for imported assignments (YYYY-MM-DD).")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, path, start_date, dry_run, **opts):
        start = datetime.date.fromisoformat(start_date)
        if path.lower().endswith(".docx"):
            records = parse_docx(path)
        elif path.lower().endswith(".csv"):
            records = parse_csv(path)
        else:
            raise CommandError("Provide a .docx or .csv file")

        stats = dict(deaneries=0, parishes=0, priests=0, assignments=0)
        deanery_order = {}
        for rec in records:
            dname = rec["deanery"] or "Unassigned"
            if dname not in deanery_order:
                deanery_order[dname] = len(deanery_order) + 1
            deanery, created = Deanery.objects.get_or_create(
                name=dname, defaults={"order": deanery_order[dname]})
            stats["deaneries"] += created
            parish, created = Parish.objects.get_or_create(
                name=rec["parish"],
                defaults=dict(deanery=deanery, kind=rec["kind"], run_by_religious=rec["religious"],
                              religious_congregation=rec["congregation"]),
            )
            stats["parishes"] += created

            for idx, raw in enumerate(rec["priests"]):
                parts = split_priest(raw)
                if not parts:
                    continue
                title, full_name, cong = parts
                priest, created = Priest.objects.get_or_create(
                    full_name__iexact=full_name,
                    defaults=dict(title=title, full_name=full_name, congregation=cong),
                )
                stats["priests"] += created
                if cong and not parish.religious_congregation:
                    parish.religious_congregation = cong
                    parish.save(update_fields=["religious_congregation"])
                if idx == 0:
                    role = (Assignment.ROLE_PARISH_PRIEST if rec["kind"] == Parish.KIND_PARISH
                            else Assignment.ROLE_ADMINISTRATOR)
                else:
                    role = Assignment.ROLE_ASSISTANT
                if not Assignment.objects.filter(priest=priest, parish=parish, end_date__isnull=True).exists():
                    Assignment.objects.create(priest=priest, parish=parish, role=role, start_date=start,
                                              note="Imported from priests list")
                    stats["assignments"] += 1

        self.stdout.write(f"Parsed {len(records)} parish/unit records.")
        self.stdout.write(self.style.SUCCESS(
            "Created: " + ", ".join(f"{v} {k}" for k, v in stats.items())))
        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("Dry run – nothing saved."))
