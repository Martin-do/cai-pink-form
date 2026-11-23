"""PDF and Excel exports for quarterly returns and diocesan summaries."""
from io import BytesIO

import openpyxl
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from openpyxl.styles import Alignment, Font, PatternFill
from xhtml2pdf import pisa

from directory.access import approved_required, can_view_parish, chancery_required
from directory.models import Parish

from . import services
from .models import QuarterlyReturn, ReportingPeriod


def _money(val):
    return float(val or 0)


@approved_required
def export_return_pdf(request, pk):
    ret = get_object_or_404(
        QuarterlyReturn.objects.select_related("parish", "period", "parish__deanery"), pk=pk
    )
    if not can_view_parish(request.user, ret.parish):
        raise PermissionDenied
    sheet = services.build_sheet(ret)
    html = render_to_string(
        "returns/pdf.html",
        {
            "ret": ret,
            "parish": ret.parish,
            "period": ret.period,
            "sheet": sheet,
            "months": ret.period.month_names,
            "diocese": settings.DIOCESE_NAME,
            "currency": settings.CURRENCY_SYMBOL,
            "priest": ret.parish.parish_priest(),
        },
    )
    buf = BytesIO()
    status = pisa.CreatePDF(html, dest=buf, encoding="utf-8")
    if status.err:
        return HttpResponse("Could not generate PDF.", status=500)
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    filename = f"{ret.parish.name[:40].replace(' ', '_')}_{ret.period}.pdf".replace(" ", "_")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@approved_required
def export_return_xlsx(request, pk):
    ret = get_object_or_404(
        QuarterlyReturn.objects.select_related("parish", "period", "parish__deanery"), pk=pk
    )
    if not can_view_parish(request.user, ret.parish):
        raise PermissionDenied
    sheet = services.build_sheet(ret)
    wb = openpyxl.Workbook()
    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="FCE4EC")
    money_fmt = "#,##0.00"

    # 1. Balance & Cathedraticum
    ws = wb.active
    ws.title = "Balance & Levy"
    ws["A1"] = settings.DIOCESE_NAME.upper()
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"{ret.period.label} QUARTERLY PARISH RETURN"
    ws["A2"].font = bold
    ws["A4"] = f"Parish: {ret.parish.name} ({ret.parish.deanery})"
    ws["A5"] = f"Status: {ret.get_status_display()} | Prepared by: {ret.prepared_by or '—'}"

    summary_rows = [
        ("Opening balance brought forward", _money(ret.opening_balance)),
        ("Total income for the period", _money(ret.total_income)),
        ("Total funds available", _money(ret.opening_balance + ret.total_income)),
        ("Total expenditure for the period", _money(ret.total_expenditure)),
        ("Closing balance / (deficit)", _money(ret.closing_balance)),
        ("Quarterly surplus / (deficit)", _money(ret.surplus)),
        ("", ""),
        ("Income subject to Cathedraticum", _money(ret.levyable_income)),
        ("Cathedraticum rate", f"{ret.levy_rate * 100:.2f}%"),
        ("Cathedraticum due", _money(ret.levy_due)),
        ("Waiver", _money(ret.waiver_amount)),
        ("Net Cathedraticum payable", _money(ret.net_levy)),
        ("Payments recorded", _money(ret.amount_paid)),
        ("Balance outstanding", _money(ret.levy_outstanding)),
    ]
    for idx, (label, val) in enumerate(summary_rows, start=7):
        ws.cell(idx, 1, label).font = bold if "Total" in label or "Closing" in label or "Net" in label else Font()
        c = ws.cell(idx, 2, val)
        if isinstance(val, float):
            c.number_format = money_fmt
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 22

    # 2. Income
    wi = wb.create_sheet("Income")
    wi.append(["Code", "Group", "Income Source", "Central (₦)", "Outstation (₦)", "Other (₦)", "Total (₦)", "Levyable"])
    for cell in wi[1]:
        cell.font = bold
        cell.fill = header_fill
    for grp, rows in sheet["income_groups"].items():
        for r in rows:
            li = r["line"]
            q = r["quarter"]
            wi.append([
                li.code, grp, li.label,
                _money(q["central"]), _money(q["outstation"]), _money(q["other"]),
                _money(r["total"]), "Yes" if li.is_levyable else "No",
            ])
    for row in wi.iter_rows(min_row=2, min_col=4, max_col=7):
        for c in row:
            c.number_format = money_fmt
    wi.column_dimensions["B"].width = 28
    wi.column_dimensions["C"].width = 42

    # 3. Expenditure
    we = wb.create_sheet("Expenditure")
    mnames = ret.period.month_names
    we.append(["Code", "Group", "Expenditure Heading", mnames[0], mnames[1], mnames[2], "Total (₦)", "Notes"])
    for cell in we[1]:
        cell.font = bold
        cell.fill = header_fill
    for grp, rows in sheet["expense_groups"].items():
        for r in rows:
            li = r["line"]
            we.append([
                li.code, grp, li.label,
                _money(r["months"][0]["amount"]),
                _money(r["months"][1]["amount"]),
                _money(r["months"][2]["amount"]),
                _money(r["total"]),
                "; ".join(r["notes"]),
            ])
    for row in we.iter_rows(min_row=2, min_col=4, max_col=7):
        for c in row:
            c.number_format = money_fmt
    we.column_dimensions["B"].width = 28
    we.column_dimensions["C"].width = 42

    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"{ret.parish.name[:40].replace(' ', '_')}_{ret.period}.xlsx".replace(" ", "_")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@chancery_required
def export_period_xlsx(request, period_id):
    period = get_object_or_404(ReportingPeriod, pk=period_id)
    parishes = Parish.objects.filter(active=True, submits_returns=True).select_related("deanery")
    returns = {
        r.parish_id: r
        for r in QuarterlyReturn.objects.filter(period=period).prefetch_related("payments")
    }

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Q{period.quarter} {period.year}"
    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="FCE4EC")
    money_fmt = "#,##0.00"

    ws["A1"] = f"{settings.DIOCESE_NAME.upper()} – {period.label} SUMMARY"
    ws["A1"].font = Font(bold=True, size=13)
    headers = [
        "Deanery", "Parish", "Status", "Opening Bal (₦)", "Income (₦)",
        "Expenditure (₦)", "Surplus / (Deficit) (₦)", "Closing Bal (₦)",
        "Levyable Income (₦)", "Cathedraticum Due (₦)", "Waiver (₦)",
        "Net Levy (₦)", "Paid (₦)", "Outstanding (₦)",
    ]
    ws.append([])
    ws.append(headers)
    for c in ws[3]:
        c.font = bold
        c.fill = header_fill
        c.alignment = Alignment(wrap_text=True)

    for p in parishes:
        r = returns.get(p.id)
        if r:
            ws.append([
                p.deanery.name, p.name, r.get_status_display(),
                _money(r.opening_balance), _money(r.total_income),
                _money(r.total_expenditure), _money(r.surplus), _money(r.closing_balance),
                _money(r.levyable_income), _money(r.levy_due), _money(r.waiver_amount),
                _money(r.net_levy), _money(r.amount_paid), _money(r.levy_outstanding),
            ])
        else:
            ws.append([p.deanery.name, p.name, "Overdue" if period.is_overdue else "Not started"] + [0.0] * 11)

    for row in ws.iter_rows(min_row=4, min_col=4, max_col=14):
        for c in row:
            c.number_format = money_fmt
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 38

    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="Diocese_Summary_Q{period.quarter}_{period.year}.xlsx"'
    return resp
