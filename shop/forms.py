import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .extra_models import CustomerProfile
from .iran_locations import province_choices, valid_city
from .models import Order, PaymentReceipt

User = get_user_model()


def normalize_mobile(value):
    value = str(value or "")
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    value = value.translate(str.maketrans(fa + ar, "0123456789" * 2))
    value = re.sub(r"\D", "", value)
    if value.startswith("0098"):
        value = "0" + value[4:]
    elif value.startswith("98"):
        value = "0" + value[2:]
    return value


class EmailLookupForm(forms.Form):
    email = forms.EmailField(
        label="ایمیل",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True, "class": "form-control", "placeholder": "example@gmail.com"}),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class PasswordOnlyForm(forms.Form):
    password = forms.CharField(
        label="رمز عبور",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "autofocus": True, "class": "form-control", "placeholder": "رمز عبور"}),
    )


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(label="نام", max_length=60)
    last_name = forms.CharField(label="نام خانوادگی", max_length=80)
    phone = forms.CharField(label="شماره تلفن همراه", max_length=20)
    email = forms.EmailField(label="ایمیل")
    accept_terms = forms.BooleanField(label="پذیرش قوانین و مقررات", required=True)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone", "email", "password1", "password2", "accept_terms")

    def __init__(self, *args, fixed_email=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_email = (fixed_email or "").strip().lower()
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["first_name"].widget.attrs.update({"placeholder": "نام", "autocomplete": "given-name"})
        self.fields["last_name"].widget.attrs.update({"placeholder": "نام خانوادگی", "autocomplete": "family-name"})
        self.fields["phone"].widget.attrs.update({"placeholder": "09xxxxxxxxx", "autocomplete": "tel", "inputmode": "tel", "dir": "ltr"})
        self.fields["password1"].label = "رمز عبور"
        self.fields["password2"].label = "تکرار رمز عبور"
        self.fields["password1"].widget.attrs.update({"placeholder": "رمز عبور", "autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"placeholder": "تکرار رمز عبور", "autocomplete": "new-password"})
        self.fields["accept_terms"].widget.attrs["class"] = "terms-checkbox"
        if self.fixed_email:
            self.fields["email"].initial = self.fixed_email
            self.fields["email"].disabled = True
            self.fields["email"].widget = forms.HiddenInput()

    def clean_email(self):
        email = (self.fixed_email or self.cleaned_data["email"]).strip().lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("این ایمیل قبلاً ثبت شده است.")
        return email

    def clean_phone(self):
        value = normalize_mobile(self.cleaned_data.get("phone"))
        if not re.fullmatch(r"09\d{9}", value):
            raise forms.ValidationError("شماره موبایل معتبر نیست؛ مثال: 09123456789")
        if CustomerProfile.objects.filter(phone=value).exists():
            raise forms.ValidationError("این شماره موبایل قبلاً برای یک حساب ثبت شده است.")
        return value

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = user.email
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.is_active = False
        if commit:
            user.save()
            CustomerProfile.ensure(user, self.cleaned_data["phone"])
        return user


class CheckoutForm(forms.ModelForm):
    province = forms.ChoiceField(label="استان", choices=())
    city = forms.CharField(label="شهر", max_length=80)
    accept_terms = forms.BooleanField(label="قوانین و مقررات را می‌پذیرم", required=True)

    class Meta:
        model = Order
        fields = ["full_name", "mobile", "email", "province", "city", "postal_code", "address", "note", "payment_method"]
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "نام و نام خانوادگی"}),
            "mobile": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel", "placeholder": "09xxxxxxxxx"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "example@gmail.com"}),
            "postal_code": forms.TextInput(attrs={"autocomplete": "postal-code", "inputmode": "numeric", "maxlength": "10", "placeholder": "کد پستی ۱۰ رقمی"}),
            "address": forms.Textarea(attrs={"rows": 4, "autocomplete": "street-address", "placeholder": "خیابان، کوچه، پلاک و واحد"}),
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": "توضیحی برای سفارش دارید؟"}),
        }

    def __init__(self, *args, store_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].label = "نام و نام خانوادگی"
        self.fields["mobile"].label = "شماره همراه"
        self.fields["email"].label = "ایمیل (اختیاری)"
        self.fields["province"].choices = [("", "انتخاب استان")] + province_choices()
        self.fields["postal_code"].label = "کد پستی"
        self.fields["address"].label = "آدرس کامل"
        self.fields["note"].label = "یادداشت سفارش (اختیاری)"
        self.fields["payment_method"].label = "روش پرداخت"
        if store_settings:
            choices = []
            if store_settings.payment_mode in ("zarinpal", "both") and store_settings.zarinpal_merchant_id:
                choices.append(("zarinpal", "پرداخت آنلاین زرین‌پال"))
            if store_settings.payment_mode in ("card", "both"):
                choices.append(("card", "کارت به کارت و آپلود رسید"))
            self.fields["payment_method"].choices = choices
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for name in ["full_name", "mobile", "province", "city", "postal_code", "address", "payment_method"]:
            self.fields[name].required = True

    def clean_mobile(self):
        value = normalize_mobile(self.cleaned_data["mobile"])
        if not re.fullmatch(r"09\d{9}", value):
            raise forms.ValidationError("شماره موبایل معتبر نیست.")
        return value

    def clean_postal_code(self):
        value = (self.cleaned_data.get("postal_code") or "").strip()
        fa = "۰۱۲۳۴۵۶۷۸۹"
        ar = "٠١٢٣٤٥٦٧٨٩"
        value = value.translate(str.maketrans(fa + ar, "0123456789" * 2))
        value = re.sub(r"\D", "", value)
        if len(value) != 10:
            raise forms.ValidationError("کد پستی باید دقیقاً ۱۰ رقم باشد.")
        return value

    def clean(self):
        cleaned = super().clean()
        province = cleaned.get("province")
        city = (cleaned.get("city") or "").strip()
        if province and city and not valid_city(province, city):
            self.add_error("city", "شهر انتخاب‌شده مربوط به این استان نیست.")
        return cleaned


class ReceiptForm(forms.ModelForm):
    class Meta:
        model = PaymentReceipt
        fields = ["image"]
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"})}

    def clean_image(self):
        image = self.cleaned_data["image"]
        if image.size > 8 * 1024 * 1024:
            raise forms.ValidationError("حجم رسید نباید بیشتر از ۸ مگابایت باشد.")
        if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("فقط فرمت JPG، PNG یا WEBP مجاز است.")
        return image
