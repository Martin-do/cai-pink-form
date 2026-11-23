from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .models import AccountProfile, Assignment, Parish, Priest

User = get_user_model()


class SignupForm(forms.Form):
    full_name = forms.CharField(
        label="Full name (as on the Archdiocesan priests list)", max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Fr. Julius Akinyode"}),
    )
    email = forms.EmailField(label="Email address")
    phone = forms.CharField(max_length=30, required=False, label="Phone number")
    claimed_parish = forms.ModelChoiceField(
        queryset=Parish.objects.filter(active=True), required=False,
        label="Parish you currently head", empty_label="— select —",
    )
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Try logging in.")
        return email

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get("password1"), cd.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        if p1:
            try:
                validate_password(p1)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cd

    def save(self):
        cd = self.cleaned_data
        parts = cd["full_name"].split()
        user = User.objects.create_user(
            username=cd["email"], email=cd["email"], password=cd["password1"],
            first_name=" ".join(parts[:-1])[:150] if len(parts) > 1 else cd["full_name"][:150],
            last_name=parts[-1][:150] if len(parts) > 1 else "",
        )
        AccountProfile.objects.create(
            user=user, phone=cd["phone"], name_as_listed=cd["full_name"],
            claimed_parish=cd["claimed_parish"],
        )
        return user


class ApproveSignupForm(forms.Form):
    priest = forms.ModelChoiceField(
        queryset=Priest.objects.filter(active=True, user__isnull=True),
        label="Link to priest record",
    )
    note = forms.CharField(max_length=255, required=False)


class TransferForm(forms.Form):
    priest = forms.ModelChoiceField(queryset=Priest.objects.filter(active=True))
    parish = forms.ModelChoiceField(queryset=Parish.objects.filter(active=True), label="New parish")
    role = forms.ChoiceField(choices=Assignment.ROLE_CHOICES, initial=Assignment.ROLE_PARISH_PRIEST)
    start_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))
    end_current = forms.BooleanField(
        required=False, initial=True,
        label="End this priest's current assignments (the day before the start date)",
    )
    end_incumbent = forms.BooleanField(
        required=False, initial=True,
        label="End the assignment of whoever currently holds this role at the new parish",
    )
    note = forms.CharField(max_length=200, required=False)


class EndAssignmentForm(forms.Form):
    end_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))


class PriestForm(forms.ModelForm):
    class Meta:
        model = Priest
        fields = ["title", "full_name", "congregation", "phone", "email", "active"]


class ParishForm(forms.ModelForm):
    class Meta:
        model = Parish
        fields = ["name", "deanery", "kind", "run_by_religious", "religious_congregation",
                  "submits_returns", "email", "phone", "active"]
