import datetime
import difflib

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from returns.models import AuditLog

from .access import chancery_required, is_chancery, linked_priest
from .forms import (
    ApproveSignupForm, EndAssignmentForm, ParishForm, PriestForm, SignupForm, TransferForm,
)
from .models import AccountProfile, Assignment, Deanery, Parish, Priest


def _safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return fallback


# ---------------------------------------------------------------- public
@login_required
def home(request):
    if is_chancery(request.user):
        return redirect("chancery_dashboard")
    if linked_priest(request.user) is None:
        return redirect("pending")
    return redirect("my_dashboard")


def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="directory.backends.EmailOrUsernameBackend")
        messages.success(request, "Your account has been created and is awaiting Chancery approval.")
        return redirect("pending")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def pending(request):
    if is_chancery(request.user) or linked_priest(request.user):
        return redirect("home")
    profile = getattr(request.user, "profile", None)
    return render(request, "registration/pending.html", {"profile": profile})


# ---------------------------------------------------------------- chancery: sign-ups
def _suggest_priests(name, limit=5):
    priests = list(Priest.objects.filter(active=True, user__isnull=True))
    clean = name.lower()
    for t in ("very rev.", "rev.", "msgr.", "msgr", "fr.", "fr "):
        clean = clean.replace(t, "")
    clean = clean.strip()
    return sorted(
        priests,
        key=lambda p: difflib.SequenceMatcher(None, clean, p.full_name.lower()).ratio(),
        reverse=True,
    )[:limit]


@chancery_required
def signup_list(request):
    status = request.GET.get("status", AccountProfile.STATUS_PENDING)
    profiles = AccountProfile.objects.filter(status=status).select_related(
        "user", "claimed_parish").order_by("-created_at")
    rows = []
    for p in profiles:
        suggestions = _suggest_priests(p.name_as_listed) if status == AccountProfile.STATUS_PENDING else []
        form = ApproveSignupForm(prefix=f"p{p.pk}",
                                 initial={"priest": suggestions[0].pk if suggestions else None})
        rows.append({"profile": p, "suggestions": suggestions, "form": form,
                     "linked": getattr(p.user, "priest", None)})
    return render(request, "chancery/signups.html", {"rows": rows, "status": status,
                                                      "statuses": AccountProfile.STATUS_CHOICES})


@chancery_required
@require_POST
@transaction.atomic
def signup_decide(request, pk):
    profile = get_object_or_404(AccountProfile, pk=pk)
    action = request.POST.get("action")
    if action == "approve":
        form = ApproveSignupForm(request.POST, prefix=f"p{pk}")
        if not form.is_valid():
            messages.error(request, "Select a priest record to link (it must not already have an account).")
            return redirect("signup_list")
        priest = form.cleaned_data["priest"]
        priest.user = profile.user
        priest.email = priest.email or profile.user.email
        priest.phone = priest.phone or profile.phone
        priest.save()
        profile.user.is_active = True
        profile.user.save(update_fields=["is_active"])
        profile.status = AccountProfile.STATUS_APPROVED
        profile.review_note = form.cleaned_data["note"]
        AuditLog.objects.create(actor=request.user, action="account_approved",
                                detail=f"{profile.user.email} linked to {priest}")
        messages.success(request, f"{profile.user.email} approved and linked to {priest}.")
    elif action == "reject":
        profile.status = AccountProfile.STATUS_REJECTED
        profile.review_note = request.POST.get("note", "")[:255]
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        AuditLog.objects.create(actor=request.user, action="account_rejected",
                                detail=f"{profile.user.email}: {profile.review_note}")
        messages.info(request, f"{profile.user.email} rejected.")
    else:
        return redirect("signup_list")
    profile.reviewed_by = request.user
    profile.reviewed_at = timezone.now()
    profile.save()
    return redirect("signup_list")


# ---------------------------------------------------------------- chancery: priests
def _with_active_assignments(qs, related):
    return qs.prefetch_related(
        Prefetch("assignments", queryset=Assignment.objects.filter(Assignment.active_q())
                 .select_related(*related), to_attr="active_assignments"))


@chancery_required
def priest_list(request):
    q = request.GET.get("q", "").strip()
    priests = _with_active_assignments(Priest.objects.select_related("user"), ["parish"])
    if q:
        priests = priests.filter(Q(full_name__icontains=q) | Q(congregation__icontains=q)
                                 | Q(assignments__parish__name__icontains=q)).distinct()
    flt = request.GET.get("f", "")
    if flt == "linked":
        priests = priests.filter(user__isnull=False)
    elif flt == "unlinked":
        priests = priests.filter(user__isnull=True)
    priests = list(priests)
    if flt == "unassigned":
        priests = [p for p in priests if not p.active_assignments]
    return render(request, "chancery/priests.html", {"priests": priests, "q": q, "f": flt})


@chancery_required
def priest_detail(request, pk):
    priest = get_object_or_404(Priest, pk=pk)
    form = PriestForm(request.POST or None, instance=priest)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Priest details updated.")
        return redirect("priest_detail", pk=pk)
    return render(request, "chancery/priest_detail.html", {
        "priest": priest, "form": form,
        "assignments": priest.assignments.select_related("parish").order_by("-start_date"),
        "end_form": EndAssignmentForm(),
    })


@chancery_required
def priest_create(request):
    form = PriestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        p = form.save()
        messages.success(request, f"{p} added.")
        return redirect("priest_detail", pk=p.pk)
    return render(request, "chancery/simple_form.html", {"form": form, "title": "Add priest"})


@chancery_required
@require_POST
def priest_unlink(request, pk):
    priest = get_object_or_404(Priest, pk=pk)
    if priest.user:
        AuditLog.objects.create(actor=request.user, action="account_unlinked",
                                detail=f"{priest.user.email} unlinked from {priest}")
        priest.user = None
        priest.save(update_fields=["user"])
        messages.info(request, "Portal account unlinked. That login no longer has parish access.")
    return redirect("priest_detail", pk=pk)


@chancery_required
def transfer(request):
    form = TransferForm(request.POST or None, initial={
        "priest": request.GET.get("priest"), "parish": request.GET.get("parish")})
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        start = cd["start_date"]
        day_before = start - datetime.timedelta(days=1)
        ended = []
        with transaction.atomic():
            to_end = []
            if cd["end_current"]:
                to_end += list(cd["priest"].assignments.filter(Assignment.active_q(start)))
            if cd["end_incumbent"] and cd["role"] in Assignment.HEAD_ROLES:
                to_end += list(cd["parish"].assignments.filter(
                    Assignment.active_q(start), role__in=Assignment.HEAD_ROLES).exclude(priest=cd["priest"]))
            for a in to_end:
                a.end_date = max(day_before, a.start_date)
                a.save(update_fields=["end_date"])
                ended.append(str(a))
            new = Assignment.objects.create(priest=cd["priest"], parish=cd["parish"], role=cd["role"],
                                            start_date=start, note=cd["note"])
            AuditLog.objects.create(actor=request.user, action="transfer",
                                    detail=f"New: {new} from {start}. Ended: {'; '.join(ended) or 'none'}")
        messages.success(request, f"{cd['priest']} assigned to {cd['parish']} from {start:%d %b %Y}.")
        return redirect("priest_detail", pk=cd["priest"].pk)
    return render(request, "chancery/simple_form.html", {
        "form": form, "title": "Assign / transfer a priest",
        "help": "Access to a parish's returns follows the assignment: the old parish disappears from "
                "the priest's portal when the old assignment ends, and the new parish appears "
                "from the start date. Past returns stay with the parish.",
    })


@chancery_required
@require_POST
def assignment_end(request, pk):
    a = get_object_or_404(Assignment, pk=pk)
    form = EndAssignmentForm(request.POST)
    if form.is_valid():
        end = form.cleaned_data["end_date"]
        if end < a.start_date:
            messages.error(request, "End date cannot be before the start date.")
        else:
            a.end_date = end
            a.save(update_fields=["end_date"])
            AuditLog.objects.create(actor=request.user, action="assignment_ended",
                                    detail=f"{a} ended {a.end_date}")
            messages.success(request, "Assignment ended.")
    return _safe_next(request, redirect("priest_detail", pk=a.priest_id))


# ---------------------------------------------------------------- chancery: parishes
@chancery_required
def parish_list(request):
    q = request.GET.get("q", "").strip()
    parishes = _with_active_assignments(Parish.objects.select_related("deanery"),
                                        ["priest", "priest__user"])
    if q:
        parishes = parishes.filter(name__icontains=q)
    deanery = request.GET.get("deanery", "")
    if deanery:
        parishes = parishes.filter(deanery_id=deanery)
    return render(request, "chancery/parishes.html", {
        "parishes": parishes, "q": q, "deaneries": Deanery.objects.all(), "deanery": deanery})


@chancery_required
def parish_detail(request, pk):
    parish = get_object_or_404(Parish, pk=pk)
    form = ParishForm(request.POST or None, instance=parish)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Parish updated.")
        return redirect("parish_detail", pk=pk)
    return render(request, "chancery/parish_detail.html", {
        "parish": parish, "form": form,
        "assignments": parish.assignments.select_related("priest").order_by("-start_date"),
        "returns": parish.returns.select_related("period").order_by("-period__year", "-period__quarter"),
        "end_form": EndAssignmentForm(),
    })


@chancery_required
def parish_create(request):
    form = ParishForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        p = form.save()
        messages.success(request, f"{p} added.")
        return redirect("parish_detail", pk=p.pk)
    return render(request, "chancery/simple_form.html", {"form": form, "title": "Add parish"})
