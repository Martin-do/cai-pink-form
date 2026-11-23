from django.conf import settings

from .access import is_chancery, linked_priest


def _initials(name):
    if not name:
        return "CA"
    skip = {"fr.", "fr", "msgr.", "msgr", "rev.", "rev", "col.", "col", "very"}
    words = [w.strip(".,") for w in name.split() if w.lower() not in skip]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words and len(words[0]) >= 2:
        return words[0][:2].upper()
    return name[:2].upper()


def portal(request):
    user = request.user
    chancery = is_chancery(user)
    ctx = {
        "DIOCESE_NAME": settings.DIOCESE_NAME,
        "CURRENCY": settings.CURRENCY_SYMBOL,
        "is_chancery": chancery,
        "user_display_name": "",
        "user_initials": "CA",
        "user_role_label": "Chancery Admin" if chancery else "Parish Priest",
    }
    if user.is_authenticated:
        priest = linked_priest(user)
        if priest:
            display = str(priest)
        else:
            display = user.get_full_name() or user.email or user.username
        ctx["user_display_name"] = display
        ctx["user_initials"] = _initials(display)
    if chancery:
        from .models import AccountProfile

        ctx["pending_signups"] = AccountProfile.objects.filter(
            status=AccountProfile.STATUS_PENDING
        ).count()
    return ctx
