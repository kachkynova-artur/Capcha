from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import captcha
from .forms import LoginForm, ProfileForm, RegisterForm


def _safe_next(request):
    """Возвращает параметр next, только если он ведёт на наш же сайт."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return None


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect("profile")

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            messages.success(request, "Вы успешно вошли в систему.")
            return redirect(_safe_next(request) or "profile")
        # Очищаем поле капчи, чтобы пользователь ввёл ответ на новый пример
        data = request.POST.copy()
        data["captcha"] = ""
        form.data = data
    else:
        form = LoginForm(request)

    captcha.generate(request)  # при каждом показе формы — новый пример
    return render(request, "accounts/login.html", {"form": form, "next": _safe_next(request) or ""})


@never_cache
def captcha_image(request):
    question = request.session.get(captcha.SESSION_QUESTION)
    if not question:
        question = captcha.generate(request)
    return HttpResponse(captcha.render_svg(question), content_type="image/svg+xml")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("profile")
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Регистрация прошла успешно. Теперь войдите в систему.")
            return redirect("login")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Вы вышли из системы.")
    return redirect("login")


@login_required
def profile_view(request):
    return render(request, "accounts/profile.html", {"has_reports": bool(_report_files())})


@login_required
def profile_edit_view(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Данные профиля сохранены.")
            return redirect("profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile_edit.html", {"form": form})


def _report_files():
    reports_dir = Path(settings.REPORTS_DIR)
    if not reports_dir.exists():
        return []
    return sorted(reports_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime)


@login_required
def download_latest_report(request):
    """Скачать последний Word-отчёт о тестировании."""
    files = _report_files()
    if not files:
        raise Http404("Отчётов пока нет. Запустите: python manage.py test")
    latest = files[-1]
    return FileResponse(open(latest, "rb"), as_attachment=True, filename=latest.name)
