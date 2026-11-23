"""Business logic: calculations, carry-forward, and the return lifecycle."""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import (
    AuditLog,
    ExpenseEntry,
    IncomeEntry,
    LineItem,
    QuarterlyReturn,
    ReportingPeriod,
)

ZERO = Decimal("0.00")


class ReturnLocked(Exception):
    pass


def to_decimal(value):
    if value in (None, ""):
        return ZERO
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"'{value}' is not a valid amount")
    if d < 0:
        raise ValueError("Amounts cannot be negative")
    return d.quantize(Decimal("0.01"))


def log(ret, actor, action, detail=""):
    AuditLog.objects.create(ret=ret, actor=actor, action=action, detail=detail)


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------
def build_sheet(ret):
    """Full pink-sheet breakdown for display/export.

    Returns dict with grouped income/expense rows, monthly totals and summary.
    """
    income_lines = list(LineItem.objects.filter(kind=LineItem.KIND_INCOME, active=True))
    expense_lines = list(LineItem.objects.filter(kind=LineItem.KIND_EXPENSE, active=True))
    inc = {(e.line_id, e.month): e for e in ret.income_entries.all()}
    exp = {(e.line_id, e.month): e for e in ret.expense_entries.all()}

    # Include inactive lines that still carry data (historic returns stay complete)
    used_inactive = LineItem.objects.filter(active=False, pk__in=[k[0] for k in list(inc) + list(exp)])
    for li in used_inactive:
        (income_lines if li.kind == LineItem.KIND_INCOME else expense_lines).append(li)

    income_groups = OrderedDict()
    month_income = [ZERO, ZERO, ZERO]
    col_totals = {"central": ZERO, "outstation": ZERO, "other": ZERO}
    levyable = ZERO
    for li in income_lines:
        months = []
        q = {"central": ZERO, "outstation": ZERO, "other": ZERO}
        notes = []
        for m in (1, 2, 3):
            e = inc.get((li.id, m))
            c = e.central if e else ZERO
            o = e.outstation if e else ZERO
            x = e.other if e else ZERO
            months.append({"central": c, "outstation": o, "other": x, "total": c + o + x,
                           "note": e.note if e else ""})
            q["central"] += c
            q["outstation"] += o
            q["other"] += x
            month_income[m - 1] += c + o + x
            if e and e.note:
                notes.append(e.note)
        total = q["central"] + q["outstation"] + q["other"]
        for k in col_totals:
            col_totals[k] += q[k]
        if li.is_levyable:
            levyable += total
        income_groups.setdefault(li.group, []).append(
            {"line": li, "months": months, "quarter": q, "total": total, "notes": notes}
        )

    expense_groups = OrderedDict()
    month_expense = [ZERO, ZERO, ZERO]
    for li in expense_lines:
        months = []
        notes = []
        for m in (1, 2, 3):
            e = exp.get((li.id, m))
            a = e.amount if e else ZERO
            months.append({"amount": a, "note": e.note if e else ""})
            month_expense[m - 1] += a
            if e and e.note:
                notes.append(e.note)
        expense_groups.setdefault(li.group, []).append(
            {"line": li, "months": months, "total": sum(x["amount"] for x in months), "notes": notes}
        )

    total_income = sum(month_income)
    total_expenditure = sum(month_expense)
    rate = ret.period.levy_rate
    summary = {
        "opening_balance": ret.opening_balance,
        "total_income": total_income,
        "funds_available": ret.opening_balance + total_income,
        "total_expenditure": total_expenditure,
        "closing_balance": ret.opening_balance + total_income - total_expenditure,
        "surplus": total_income - total_expenditure,
        "levyable_income": levyable,
        "levy_rate": rate,
        "levy_due": (levyable * rate).quantize(Decimal("0.01")),
        "income_columns": col_totals,
    }
    return {
        "income_groups": income_groups,
        "expense_groups": expense_groups,
        "month_income": month_income,
        "month_expense": month_expense,
        "month_net": [i - e for i, e in zip(month_income, month_expense)],
        "summary": summary,
    }


def refresh_totals(ret, sheet=None):
    s = (sheet or build_sheet(ret))["summary"]
    ret.total_income = s["total_income"]
    ret.total_expenditure = s["total_expenditure"]
    ret.closing_balance = s["closing_balance"]
    ret.levyable_income = s["levyable_income"]
    ret.levy_rate = s["levy_rate"]
    ret.levy_due = s["levy_due"]
    ret.save(update_fields=[
        "total_income", "total_expenditure", "closing_balance",
        "levyable_income", "levy_rate", "levy_due", "updated_at",
    ])


# --------------------------------------------------------------------------
# Carry-forward
# --------------------------------------------------------------------------
def previous_return(ret):
    prev_period = ret.period.previous()
    if not prev_period:
        return None
    return QuarterlyReturn.objects.filter(parish=ret.parish, period=prev_period).first()


def apply_carry_forward(ret):
    """Opening balance = previous quarter's closing balance, if that was filed."""
    prev = previous_return(ret)
    if prev and prev.is_filed:
        ret.opening_balance = prev.closing_balance
        ret.opening_balance_carried = True
    else:
        ret.opening_balance_carried = False
    return ret


def get_or_start_return(parish, period, user):
    ret, created = QuarterlyReturn.objects.get_or_create(
        parish=parish, period=period, defaults={"created_by": user}
    )
    if created:
        apply_carry_forward(ret)
        ret.save()
        log(ret, user, "created", "Draft return started")
    elif ret.is_editable:
        before = (ret.opening_balance, ret.opening_balance_carried)
        apply_carry_forward(ret)
        if (ret.opening_balance, ret.opening_balance_carried) != before:
            ret.save(update_fields=["opening_balance", "opening_balance_carried", "updated_at"])
    return ret


# --------------------------------------------------------------------------
# Saving entries
# --------------------------------------------------------------------------
@transaction.atomic
def save_entries(ret, data, user):
    """Save a draft from POST-like data. Raises ReturnLocked / ValueError.

    Field names:
      inc-<line>-<m>-c / -o / -x / -n   (central, outstation, other, note)
      exp-<line>-<m>-a / -n             (amount, note)
      opening_balance, prepared_by, remarks
    """
    ret = QuarterlyReturn.objects.select_for_update().get(pk=ret.pk)
    if not ret.is_editable:
        raise ReturnLocked("This return has been submitted and can no longer be edited.")

    errors = []
    lines = {li.id: li for li in LineItem.objects.filter(active=True)}

    def amount(name):
        try:
            return to_decimal(data.get(name))
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            return ZERO

    if not ret.opening_balance_carried and "opening_balance" in data:
        raw = (data.get("opening_balance") or "0").replace(",", "").strip()
        try:
            ret.opening_balance = Decimal(raw or "0").quantize(Decimal("0.01"))
        except InvalidOperation:
            errors.append("Opening balance is not a valid amount")
    ret.prepared_by = (data.get("prepared_by") or "")[:150]
    ret.remarks = data.get("remarks") or ""

    inc_existing = {(e.line_id, e.month): e for e in ret.income_entries.all()}
    exp_existing = {(e.line_id, e.month): e for e in ret.expense_entries.all()}
    for line_id, li in lines.items():
        for m in (1, 2, 3):
            if li.kind == LineItem.KIND_INCOME:
                p = f"inc-{line_id}-{m}"
                if f"{p}-c" not in data and f"{p}-o" not in data and f"{p}-x" not in data:
                    continue
                c, o, x = amount(f"{p}-c"), amount(f"{p}-o"), amount(f"{p}-x")
                note = (data.get(f"{p}-n") or "")[:255]
                e = inc_existing.get((line_id, m))
                if c == o == x == ZERO and not note:
                    if e:
                        e.delete()
                    continue
                e = e or IncomeEntry(ret=ret, line=li, month=m)
                e.central, e.outstation, e.other, e.note = c, o, x, note
                e.save()
            else:
                p = f"exp-{line_id}-{m}"
                if f"{p}-a" not in data:
                    continue
                a = amount(f"{p}-a")
                note = (data.get(f"{p}-n") or "")[:255]
                e = exp_existing.get((line_id, m))
                if a == ZERO and not note:
                    if e:
                        e.delete()
                    continue
                e = e or ExpenseEntry(ret=ret, line=li, month=m)
                e.amount, e.note = a, note
                e.save()

    if errors:
        transaction.set_rollback(True)
        raise ValueError("; ".join(errors[:10]))

    ret.save()
    refresh_totals(ret)
    return ret


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------
@transaction.atomic
def submit_return(ret, user):
    ret = QuarterlyReturn.objects.select_for_update().get(pk=ret.pk)
    if not ret.is_editable:
        raise ReturnLocked("This return has already been submitted.")
    if not ret.period.is_open:
        raise ReturnLocked("This reporting period is closed. Contact the Chancery.")
    was_unlocked = ret.status == QuarterlyReturn.STATUS_UNLOCKED
    refresh_totals(ret)
    ret.status = QuarterlyReturn.STATUS_SUBMITTED
    ret.submitted_by = user
    ret.submitted_at = timezone.now()
    ret.save()
    log(ret, user, "resubmitted" if was_unlocked else "submitted",
        f"Income ₦{ret.total_income:,.2f}; Expenditure ₦{ret.total_expenditure:,.2f}; "
        f"Levy due ₦{ret.levy_due:,.2f}")
    _refresh_next_quarter(ret, user)
    return ret


def _refresh_next_quarter(ret, user):
    """If the following quarter's draft exists, update its carried balance."""
    p = ret.period
    y, q = (p.year, p.quarter + 1) if p.quarter < 4 else (p.year + 1, 1)
    nxt = QuarterlyReturn.objects.filter(parish=ret.parish, period__year=y, period__quarter=q).first()
    if nxt and nxt.is_editable:
        apply_carry_forward(nxt)
        nxt.save()
        refresh_totals(nxt)


@transaction.atomic
def unlock_return(ret, user, reason):
    if not reason.strip():
        raise ValueError("A reason is required to unlock a return.")
    ret = QuarterlyReturn.objects.select_for_update().get(pk=ret.pk)
    if not ret.is_filed:
        raise ValueError("Only submitted or accepted returns can be unlocked.")
    ret.status = QuarterlyReturn.STATUS_UNLOCKED
    ret.accepted_by = None
    ret.accepted_at = None
    ret.save()
    log(ret, user, "unlocked", reason.strip())
    return ret


@transaction.atomic
def accept_return(ret, user, note=""):
    ret = QuarterlyReturn.objects.select_for_update().get(pk=ret.pk)
    if ret.status != QuarterlyReturn.STATUS_SUBMITTED:
        raise ValueError("Only submitted returns can be accepted.")
    ret.status = QuarterlyReturn.STATUS_ACCEPTED
    ret.accepted_by = user
    ret.accepted_at = timezone.now()
    ret.save()
    log(ret, user, "accepted", note)
    return ret


@transaction.atomic
def set_waiver(ret, user, waiver_type, value, reason):
    valid = dict(QuarterlyReturn.WAIVER_CHOICES)
    if waiver_type not in valid:
        raise ValueError("Unknown waiver type")
    if waiver_type != QuarterlyReturn.WAIVER_NONE and not reason.strip():
        raise ValueError("Please give a reason for the waiver.")
    value = to_decimal(value) if waiver_type in (
        QuarterlyReturn.WAIVER_AMOUNT, QuarterlyReturn.WAIVER_PERCENT) else ZERO
    if waiver_type == QuarterlyReturn.WAIVER_PERCENT and value > 100:
        raise ValueError("Percentage cannot exceed 100")
    ret.waiver_type = waiver_type
    ret.waiver_value = value
    ret.waiver_reason = reason.strip()
    ret.waived_by = user if waiver_type != QuarterlyReturn.WAIVER_NONE else None
    ret.waived_at = timezone.now() if waiver_type != QuarterlyReturn.WAIVER_NONE else None
    ret.save()
    log(ret, user, "waiver",
        f"{valid[waiver_type]} (value {value}) → waived ₦{ret.waiver_amount:,.2f}. {reason}".strip())
    return ret


def period_for_today():
    """Return the open period whose quarter most recently ended (or current)."""
    return ReportingPeriod.objects.filter(is_open=True).order_by("-year", "-quarter").first()
