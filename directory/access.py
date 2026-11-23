"""Central access-control rules. Every parish-scoped view goes through here."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import Assignment, Parish


def is_chancery(user):
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def linked_priest(user):
    return getattr(user, "priest", None) if user.is_authenticated else None


def current_parishes(user):
    """Parishes the user is currently assigned to (empty for unlinked users)."""
    priest = linked_priest(user)
    if not priest or not priest.active:
        return Parish.objects.none()
    return Parish.objects.filter(
        assignments__in=priest.assignments.filter(Assignment.active_q())
    ).distinct()


def current_assignment(user, parish):
    """The user's active assignment at this parish, preferring head roles."""
    priest = linked_priest(user)
    if not priest or not priest.active:
        return None
    active = list(priest.assignments.filter(Assignment.active_q(), parish=parish))
    heads = [a for a in active if a.can_submit]
    return (heads or active or [None])[0]


def can_view_parish(user, parish):
    return is_chancery(user) or current_assignment(user, parish) is not None


def can_edit_parish(user, parish):
    """Assigned priests (any role) may prepare drafts."""
    return current_assignment(user, parish) is not None


def can_submit_for_parish(user, parish):
    a = current_assignment(user, parish)
    return bool(a and a.can_submit)


def chancery_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not is_chancery(request.user):
            raise PermissionDenied("Chancery staff only.")
        return view(request, *args, **kwargs)

    return wrapper


def approved_required(view):
    """Logged-in, approved and linked to a priest record (or chancery)."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        user = request.user
        if is_chancery(user):
            return view(request, *args, **kwargs)
        if linked_priest(user) is None:
            return redirect("pending")
        return view(request, *args, **kwargs)

    return wrapper
