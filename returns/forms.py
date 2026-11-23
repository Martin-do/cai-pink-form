from django import forms

from .models import LevyPayment, QuarterlyReturn, ReportingPeriod


class WaiverForm(forms.Form):
    waiver_type = forms.ChoiceField(choices=QuarterlyReturn.WAIVER_CHOICES, label="Waiver")
    waiver_value = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=16,
                                      label="Amount (₦) or percentage")
    reason = forms.CharField(max_length=255, required=False,
                             widget=forms.TextInput(attrs={"placeholder": "Reason / approval reference"}))


class LevyPaymentForm(forms.ModelForm):
    class Meta:
        model = LevyPayment
        fields = ["amount", "date_paid", "method", "reference", "note"]
        widgets = {"date_paid": forms.DateInput(attrs={"type": "date"})}


class UnlockForm(forms.Form):
    reason = forms.CharField(
        max_length=500, widget=forms.Textarea(attrs={"rows": 2, "placeholder": "What must be corrected?"}))


class PeriodForm(forms.ModelForm):
    levy_percent = forms.DecimalField(label="Cathedraticum rate (%)", min_value=0, max_value=100,
                                      decimal_places=2, max_digits=5)

    class Meta:
        model = ReportingPeriod
        fields = ["year", "quarter", "due_date", "is_open"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["levy_percent"].initial = self.instance.levy_rate * 100
        else:
            self.fields["levy_percent"].initial = 25

    def save(self, commit=True):
        self.instance.levy_rate = self.cleaned_data["levy_percent"] / 100
        return super().save(commit)
