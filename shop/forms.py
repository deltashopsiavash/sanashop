import re

from django import forms

from .models import Order, PaymentReceipt


class CheckoutForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["full_name", "mobile", "email", "province", "city", "postal_code", "address", "note", "payment_method"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3}), "note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, store_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].label = "نام و نام خانوادگی"
        self.fields["mobile"].label = "شماره موبایل"
        self.fields["email"].label = "ایمیل (اختیاری)"
        self.fields["province"].label = "استان"
        self.fields["city"].label = "شهر"
        self.fields["postal_code"].label = "کد پستی"
        self.fields["address"].label = "آدرس کامل"
        self.fields["note"].label = "توضیحات (اختیاری)"
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

    def clean_mobile(self):
        value = re.sub(r"\D", "", self.cleaned_data["mobile"])
        if value.startswith("98"):
            value = "0" + value[2:]
        if not re.fullmatch(r"09\d{9}", value):
            raise forms.ValidationError("شماره موبایل معتبر نیست.")
        return value

    def clean_postal_code(self):
        value = re.sub(r"\D", "", self.cleaned_data["postal_code"])
        if len(value) != 10:
            raise forms.ValidationError("کد پستی باید ۱۰ رقم باشد.")
        return value


class ReceiptForm(forms.ModelForm):
    class Meta:
        model = PaymentReceipt
        fields = ["image"]

    def clean_image(self):
        image = self.cleaned_data["image"]
        if image.size > 8 * 1024 * 1024:
            raise forms.ValidationError("حجم رسید نباید بیشتر از ۸ مگابایت باشد.")
        if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("فقط فرمت JPG، PNG یا WEBP مجاز است.")
        return image

