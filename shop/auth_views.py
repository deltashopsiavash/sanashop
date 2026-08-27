from django.contrib.auth import views as auth_views

from .emailing import email_brand_context


class BrandedPasswordResetView(auth_views.PasswordResetView):
    """Inject live store branding into Django's normal password-reset emails."""

    def form_valid(self, form):
        self.extra_email_context = email_brand_context(request=self.request)
        return super().form_valid(form)
