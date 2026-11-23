from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """Allow logging in with either username or email (case-insensitive)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        user = User.objects.filter(
            Q(username__iexact=username.strip()) | Q(email__iexact=username.strip())
        ).first()
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
