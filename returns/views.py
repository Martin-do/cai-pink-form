from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from directory.access import (
    approved_required, can_edit_parish, can_submit_for_parish, can_view_parish,
    current_assignment, current_parishes, is_chancery,
)
from directory.models import Parish

from . import services
from .models import LineItem, QuarterlyReturn, ReportingPeriod


def _periods_visible_to_parishes():
    """Periods a parish can work on: open and already started."""
    today = timezone.localdate()
    return [p for p in ReportingPeriod.objects.filter(is_open=True) if p.start_date <= today]


@approved_required
def my_dashboard(request):
    if is_chancery(request.user) and not getattr(request.user, "priest", None):
        return redirect("chancery_dashboard")
    parishes = list(current_parishes(request.user).select_related("deanery"))
    periods = _periods_visible_to_parishes()
    cards = []
    for parish in parishes:
        returns = {r.period_id: r for r in parish.returns.select_related("period")}
        open_rows = [{"period": p, "ret": returns.get(p.id)} for p in periods]
        history = [r for r in returns.values() if r.is_filed or r.period_id not in {p.id for p in periods}]
        history.sort(key=lambda r: (r.period.year, r.period.quarter), reverse=True)
        cards.append({
            "parish": parish,
            "assignment": current_assignment(request.user, parish),
            "open_rows": open_rows,
            "history": history,
        })
    return render(request, "portal/dashboard.html", {"cards": cards, "today": timezone.localdate()})


def _can_submit_now(period):
    return timezone.localdate() >= period.end_date


@approved_required
def return_edit(request, parish_id, period_id):
    parish = get_object_or_404(Parish, pk=parish_id)
    period = get_object_or_404(ReportingPeriod, pk=period_id)
    if not can_edit_parish(request.user, parish):
        raise PermissionDenied("You are not currently assigned to this parish.")

    existing = QuarterlyReturn.objects.filter(parish=parish, period=period).first()
    if existing and not existing.is_editable:
        messages.info(request, "This return has been submitted and is locked. "
                               "Contact the Chancery if a correction is needed.")
        return redirect("return_detail", pk=existing.pk)
    if not period.is_open or period.start_date > timezone.localdate():
        messages.error(request, "This reporting period is not open for returns.")
        return redirect("my_dashboard")

    ret = services.get_or_start_return(parish, period, request.user)
    may_submit = can_submit_for_parish(request.user, parish)

    if request.method == "POST":
        action = request.POST.get("action", "save")
        try:
            services.save_entries(ret, request.POST, request.user)
        except services.ReturnLocked as exc:
            messages.error(request, str(exc))
            return redirect("return_detail", pk=ret.pk)
        except ValueError as exc:
            messages.error(request, f"Not saved – please correct: {exc}")
            return redirect(request.path + "#" + request.POST.get("tab", ""))

        if action == "submit":
            if not may_submit:
                messages.error(request, "Only the Parish Priest / Administrator can submit the return. "
                                        "Your changes have been saved as a draft.")
            elif not _can_submit_now(period):
                messages.error(request, f"The return can be submitted from {period.end_date:%d %B %Y} "
                                        "(the last day of the quarter). Your draft has been saved.")
            elif request.POST.get("confirm") != "yes":
                messages.error(request, "Please tick the confirmation box to submit.")
            else:
                try:
                    services.submit_return(ret, request.user)
                except services.ReturnLocked as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, f"{period} return submitted for {parish}. It is now locked.")
                    return redirect("return_detail", pk=ret.pk)
        else:
            messages.success(request, "Draft saved.")
        return redirect(request.path + ("#" + request.POST["tab"] if request.POST.get("tab") else ""))

    ret.refresh_from_db()
    sheet = services.build_sheet(ret)
    prev = services.previous_return(ret)
    return render(request, "returns/edit.html", {
        "ret": ret, "parish": parish, "period": period, "sheet": sheet,
        "months": list(zip((1, 2, 3), period.month_names)),
        "may_submit": may_submit, "can_submit_now": _can_submit_now(period),
        "prev": prev, "unlock_reason": ret.audit.filter(action="unlocked").first(),
    })


@approved_required
def return_detail(request, pk):
    ret = get_object_or_404(QuarterlyReturn.objects.select_related("parish", "period", "parish__deanery"), pk=pk)
    if not can_view_parish(request.user, ret.parish):
        raise PermissionDenied("You do not have access to this parish's returns.")
    sheet = services.build_sheet(ret)
    ctx = {
        "ret": ret, "sheet": sheet, "period": ret.period, "parish": ret.parish,
        "can_edit": ret.is_editable and can_edit_parish(request.user, ret.parish),
        "audit": ret.audit.select_related("actor")[:50],
        "payments": ret.payments.select_related("recorded_by"),
    }
    if is_chancery(request.user):
        from .forms import LevyPaymentForm, UnlockForm, WaiverForm
        ctx.update({
            "waiver_form": WaiverForm(initial={"waiver_type": ret.waiver_type,
                                               "waiver_value": ret.waiver_value or "",
                                               "reason": ret.waiver_reason}),
            "payment_form": LevyPaymentForm(),
            "unlock_form": UnlockForm(),
        })
    return render(request, "returns/detail.html", ctx)


@approved_required
def parish_history(request, parish_id):
    parish = get_object_or_404(Parish, pk=parish_id)
    if not can_view_parish(request.user, parish):
        raise PermissionDenied
    returns = parish.returns.select_related("period").order_by("-period__year", "-period__quarter")
    return render(request, "returns/history.html", {"parish": parish, "returns": returns})
