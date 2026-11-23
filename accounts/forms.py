from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from . import captcha

CAPTCHA_ERROR = "Неверный ответ на капчу. Попробуйте ещё раз."


class LoginForm(AuthenticationForm):
    """Форма входа с обязательной капчей."""

    captcha = forms.CharField(
        label="Ответ с картинки",
        max_length=3,
        widget=forms.TextInput(attrs={"autocomplete": "off", "inputmode": "numeric"}),
        error_messages={"required": "Введите ответ с картинки."},
    )

    def clean(self):
        # Сначала проверяем капчу: без неё пароль даже не проверяется
        if "captcha" in self.errors:
            captcha.invalidate(self.request)
            return self.cleaned_data
        if not captcha.validate(self.request, self.cleaned_data.get("captcha")):
            self.add_error("captcha", CAPTCHA_ERROR)
            return self.cleaned_data
        return super().clean()


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label="Email", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже зарегистрирован.")
        return email


class ProfileForm(forms.ModelForm):
    email = forms.EmailField(label="Email", required=True)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "Имя", "last_name": "Фамилия"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Этот email уже занят другим пользователем.")
        return email
