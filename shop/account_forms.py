import re

from django import forms

from .extra_models import CustomerProfile
from .forms import normalize_mobile


class CustomerPhoneForm(forms.Form):
    phone = forms.CharField(
        label="شماره تلفن همراه",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "09xxxxxxxxx",
                "autocomplete": "tel",
                "inputmode": "tel",
                "dir": "ltr",
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_phone(self):
        value = normalize_mobile(self.cleaned_data.get("phone"))
        if not re.fullmatch(r"09\d{9}", value):
            raise forms.ValidationError("شماره موبایل معتبر نیست؛ مثال: 09123456789")
        duplicate = CustomerProfile.objects.filter(phone=value)
        if self.user:
            duplicate = duplicate.exclude(user=self.user)
        if duplicate.exists():
            raise forms.ValidationError("این شماره موبایل برای حساب دیگری ثبت شده است.")
        return value
