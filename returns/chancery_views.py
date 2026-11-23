"""Chancery-only views: compliance board, financial summary, unlock, waiver, payments, settings."""
from decimal import Decimal

from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from directory.access import chancery_required
from directory.models import Assignment, Deanery, Parish

from . import services
from .forms import LevyPaymentForm, PeriodForm, UnlockForm, WaiverForm
from .models import LineItem, QuarterlyReturn, ReportingPeriod


def _selected_period(request):
    pid = request.GET.get("period")
    if pid and pid.isdigit():
        p = ReportingPeriod.objects.filter(pk=int(pid)).first()
        if p:
            return p
    today = timezone.localdate()
    for p in ReportingPeriod.objects.filter(is_open=True).order_by("-year", "-quarter"):
        if p.start_date <= today:
            return p
    return ReportingPeriod.objects.order_by("-year", "-quarter").first()


@chancery_required
def chancery_dashboard(request):
    periods = list(ReportingPeriod.objects.order_by("-year", "-quarter"))
    period = _selected_period(request)
    deanery_id = request.GET.get("deanery", "")
    status_filter = request.GET.get("status", "")

    parishes = (
        Parish.objects.filter(active=True, submits_returns=True)
        .select_related("deanery")
        .prefetch_related(
            Prefetch(
                "assignments",
                queryset=Assignment.objects.filter(
                    Assignment.active_q(), role__in=Assignment.HEAD_ROLES
                ).select_related("priest"),
                to_attr="head_assignments",
            )
        )
    )
    if deanery_id:
        parishes = parishes.filter(deanery_id=deanery_id)

    returns_by_parish = {}
    if period:
        qs = QuarterlyReturn.objects.filter(period=period).prefetch_related("payments")
        returns_by_parish = {r.parish_id: r for r in qs}

    rows = []
    totals = {
        "parishes": 0,
        "filed": 0,
        "draft": 0,
        "not_started": 0,
        "overdue": 0,
        "income": Decimal("0.00"),
        "expenditure": Decimal("0.00"),
        "levy_due": Decimal("0.00"),
        "waived": Decimal("0.00"),
        "net_levy": Decimal("0.00"),
        "paid": Decimal("0.00"),
        "outstanding": Decimal("0.00"),
    }

    for p in parishes:
        ret = returns_by_parish.get(p.id)
        if ret is None:
            state = "overdue" if (period and period.is_overdue) else "not_started"
        else:
            state = ret.status

        totals["parishes"] += 1
        if ret and ret.is_filed:
            totals["filed"] += 1
        elif ret:
            totals["draft"] += 1
        else:
            totals["not_started"] += 1
        if period and period.is_overdue and (ret is None or not ret.is_filed):
            totals["overdue"] += 1

        if ret:
            totals["income"] += ret.total_income
            totals["expenditure"] += ret.total_expenditure
            totals["levy_due"] += ret.levy_due
            totals["waived"] += ret.waiver_amount
            totals["net_levy"] += ret.net_levy
            totals["paid"] += ret.amount_paid
            totals["outstanding"] += ret.levy_outstanding

        if status_filter == "filed" and not (ret and ret.is_filed):
            continue
        if status_filter == "pending" and (ret and ret.is_filed):
            continue
        if status_filter == "owed" and not (ret and ret.levy_outstanding > 0):
            continue

        head = p.head_assignments[0].priest if p.head_assignments else None
        rows.append({"parish": p, "priest": head, "ret": ret, "state": state})

    totals["surplus"] = totals["income"] - totals["expenditure"]
    totals["compliance_pct"] = (
        round((totals["filed"] / totals["parishes"]) * 100) if totals["parishes"] else 0
    )
    return render(
        request,
        "chancery/dashboard.html",
        {
            "periods": periods,
            "period": period,
            "deaneries": Deanery.objects.all(),
            "deanery_id": deanery_id,
            "status_filter": status_filter,
            "rows": rows,
            "totals": totals,
        },
    )


@chancery_required
def annual_summary(request):
    years = list(
        ReportingPeriod.objects.values_list("year", flat=True).distinct().order_by("-year")
    )
    year = int(request.GET.get("year") or (years[0] if years else timezone.localdate().year))
    periods = list(ReportingPeriod.objects.filter(year=year).order_by("quarter"))
    deanery_id = request.GET.get("deanery", "")

    parishes = Parish.objects.filter(active=True, submits_returns=True).select_related("deanery")
    if deanery_id:
        parishes = parishes.filter(deanery_id=deanery_id)

    returns = (
        QuarterlyReturn.objects.filter(period__year=year)
        .select_related("period")
        .prefetch_related("payments")
    )
    grid = {(r.parish_id, r.period.quarter): r for r in returns}

    rows = []
    grand = {
        "income": Decimal("0.00"),
        "expenditure": Decimal("0.00"),
        "surplus": Decimal("0.00"),
        "net_levy": Decimal("0.00"),
        "paid": Decimal("0.00"),
        "outstanding": Decimal("0.00"),
    }
    for p in parishes:
        q_cells = [grid.get((p.id, q)) for q in (1, 2, 3, 4)]
        filed = [r for r in q_cells if r is not None]
        inc = sum((r.total_income for r in filed), Decimal("0.00"))
        exp = sum((r.total_expenditure for r in filed), Decimal("0.00"))
        net_levy = sum((r.net_levy for r in filed), Decimal("0.00"))
        paid = sum((r.amount_paid for r in filed), Decimal("0.00"))
        out = net_levy - paid
        grand["income"] += inc
        grand["expenditure"] += exp
        grand["surplus"] += inc - exp
        grand["net_levy"] += net_levy
        grand["paid"] += paid
        grand["outstanding"] += out
        rows.append(
            {
                "parish": p,
                "quarters": q_cells,
                "income": inc,
                "expenditure": exp,
                "surplus": inc - exp,
                "net_levy": net_levy,
                "paid": paid,
                "outstanding": out,
            }
        )

    return render(
        request,
        "chancery/annual.html",
        {
            "years": years,
            "year": year,
            "periods": periods,
            "deaneries": Deanery.objects.all(),
            "deanery_id": deanery_id,
            "rows": rows,
            "grand": grand,
        },
    )


@chancery_required
@require_POST
def return_unlock(request, pk):
    ret = get_object_or_404(QuarterlyReturn, pk=pk)
    form = UnlockForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a reason to unlock this return.")
        return redirect("return_detail", pk=pk)
    try:
        services.unlock_return(ret, request.user, form.cleaned_data["reason"])
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Return unlocked for {ret.parish}. The parish can now edit and resubmit.")
    return redirect("return_detail", pk=pk)


@chancery_required
@require_POST
def return_accept(request, pk):
    ret = get_object_or_404(QuarterlyReturn, pk=pk)
    try:
        services.accept_return(ret, request.user, request.POST.get("note", ""))
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Return marked as Accepted.")
    return redirect("return_detail", pk=pk)


@chancery_required
@require_POST
def return_waive(request, pk):
    ret = get_object_or_404(QuarterlyReturn, pk=pk)
    form = WaiverForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid waiver details.")
        return redirect("return_detail", pk=pk)
    cd = form.cleaned_data
    try:
        services.set_waiver(ret, request.user, cd["waiver_type"], cd["waiver_value"] or 0, cd["reason"])
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Cathedraticum waiver updated.")
    return redirect("return_detail", pk=pk)


@chancery_required
@require_POST
def return_payment(request, pk):
    ret = get_object_or_404(QuarterlyReturn, pk=pk)
    form = LevyPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a valid payment amount and date.")
        return redirect("return_detail", pk=pk)
    payment = form.save(commit=False)
    payment.ret = ret
    payment.recorded_by = request.user
    payment.save()
    services.log(
        ret,
        request.user,
        "payment_recorded",
        f"₦{payment.amount:,.2f} ({payment.get_method_display()}) ref: {payment.reference or '—'}",
    )
    messages.success(request, f"Payment of ₦{payment.amount:,.2f} recorded.")
    return redirect("return_detail", pk=pk)


@chancery_required
def period_list(request):
    form = PeriodForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        p = form.save()
        messages.success(request, f"Saved {p.label}.")
        return redirect("period_list")
    return render(
        request,
        "chancery/periods.html",
        {"periods": ReportingPeriod.objects.order_by("-year", "-quarter"), "form": form},
    )


@chancery_required
@require_POST
def period_toggle(request, pk):
    p = get_object_or_404(ReportingPeriod, pk=pk)
    p.is_open = not p.is_open
    p.save(update_fields=["is_open"])
    messages.success(request, f"{p.label} is now {'open' if p.is_open else 'closed'}.")
    return redirect("period_list")


@chancery_required
def line_items(request):
    if request.method == "POST":
        levy_ids = {int(x) for x in request.POST.getlist("levyable")}
        active_ids = {int(x) for x in request.POST.getlist("active")}
        for li in LineItem.objects.all():
            changed = False
            if li.kind == LineItem.KIND_INCOME:
                new_levy = li.id in levy_ids
                if li.is_levyable != new_levy:
                    li.is_levyable = new_levy
                    changed = True
            new_active = li.id in active_ids
            if li.active != new_active:
                li.active = new_active
                changed = True
            if changed:
                li.save()
        messages.success(request, "Pink sheet line settings updated.")
        return redirect("line_items")
    return render(
        request,
        "chancery/line_items.html",
        {
            "income_lines": LineItem.objects.filter(kind=LineItem.KIND_INCOME),
            "expense_lines": LineItem.objects.filter(kind=LineItem.KIND_EXPENSE),
        },
    )
