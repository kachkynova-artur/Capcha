"""
Автотесты лабораторной работы.

Группы тестов:
    1. Капча
    2. Регистрация
    3. Авторизация (вход с учётом капчи, выход)
    4. Личный кабинет

Запуск:  python manage.py test accounts -v 2
После запуска отчёт сохраняется в папку reports/ в формате .docx.

Первая строка docstring каждого теста попадает в Word-отчёт как описание.
"""
import re
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from . import captcha

PASSWORD = "StrongPass!2024"


class CaptchaHelpersMixin:
    """Вспомогательные методы: получить ответ капчи и войти с ним."""

    def get_captcha_answer(self):
        # Открываем страницу входа — сервер генерирует капчу и кладёт ответ в сессию
        self.client.get(reverse("login"))
        return self.client.session[captcha.SESSION_ANSWER]

    def login_with_captcha(self, username, password, answer=None, url=None):
        if answer is None:
            answer = self.get_captcha_answer()
        return self.client.post(
            url or reverse("login"),
            {"username": username, "password": password, "captcha": answer},
        )

    def is_logged_in(self):
        return "_auth_user_id" in self.client.session


# ---------------------------------------------------------------------------
# 1. КАПЧА
# ---------------------------------------------------------------------------
class CaptchaTests(CaptchaHelpersMixin, TestCase):
    report_group = "Капча"

    def setUp(self):
        self.user = User.objects.create_user("tester", "tester@example.com", PASSWORD)

    def test_login_page_contains_captcha(self):
        """Страница входа содержит поле капчи и картинку с примером"""
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="captcha"')
        self.assertContains(response, reverse("captcha_image"))

    def test_captcha_saved_in_session(self):
        """При открытии формы входа ответ капчи сохраняется в сессии"""
        self.client.get(reverse("login"))
        session = self.client.session
        self.assertIn(captcha.SESSION_ANSWER, session)
        self.assertIn(captcha.SESSION_QUESTION, session)

    def test_captcha_answer_matches_question(self):
        """Ответ в сессии совпадает с решением показанного примера"""
        self.client.get(reverse("login"))
        session = self.client.session
        match = re.match(r"(\d+)\s*([+-])\s*(\d+)", session[captcha.SESSION_QUESTION])
        self.assertIsNotNone(match)
        a, op, b = int(match.group(1)), match.group(2), int(match.group(3))
        expected = a + b if op == "+" else a - b
        self.assertEqual(session[captcha.SESSION_ANSWER], expected)
        self.assertGreaterEqual(expected, 0)

    def test_captcha_image_is_svg(self):
        """Картинка капчи отдаётся в формате SVG и не кэшируется браузером"""
        self.client.get(reverse("login"))
        response = self.client.get(reverse("captcha_image"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("image/svg+xml"))
        self.assertIn(b"<svg", response.content)
        self.assertIn("no-store", response["Cache-Control"])

    def test_captcha_image_without_session(self):
        """Картинка капчи генерирует новый пример, если в сессии его нет"""
        response = self.client.get(reverse("captcha_image"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(captcha.SESSION_ANSWER, self.client.session)

    def test_correct_password_wrong_captcha_denied(self):
        """Верный логин и пароль, но неверная капча — вход запрещён"""
        answer = self.get_captcha_answer()
        response = self.login_with_captcha("tester", PASSWORD, answer=answer + 1)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.is_logged_in())
        self.assertIn("captcha", response.context["form"].errors)

    def test_empty_captcha_denied(self):
        """Пустая капча — вход запрещён, выводится сообщение об ошибке"""
        self.get_captcha_answer()
        response = self.login_with_captcha("tester", PASSWORD, answer="")
        self.assertFalse(self.is_logged_in())
        self.assertContains(response, "Введите ответ с картинки")

    def test_non_numeric_captcha_denied(self):
        """Нечисловой ответ на капчу — вход запрещён"""
        self.get_captcha_answer()
        response = self.login_with_captcha("tester", PASSWORD, answer="abc")
        self.assertFalse(self.is_logged_in())
        self.assertIn("captcha", response.context["form"].errors)

    def test_post_without_captcha_in_session_denied(self):
        """POST-запрос без предварительного получения капчи (бот) — вход запрещён"""
        response = self.client.post(
            reverse("login"), {"username": "tester", "password": PASSWORD, "captcha": "5"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.is_logged_in())

    def test_captcha_with_spaces_accepted(self):
        """Правильный ответ с пробелами по краям принимается"""
        answer = self.get_captcha_answer()
        self.login_with_captcha("tester", PASSWORD, answer=f"  {answer}  ")
        self.assertTrue(self.is_logged_in())

    def test_captcha_is_one_time(self):
        """Капча одноразовая: повторно использовать тот же ответ нельзя"""
        request = RequestFactory().get("/")
        request.session = SessionStore()
        captcha.generate(request)
        answer = request.session[captcha.SESSION_ANSWER]
        self.assertTrue(captcha.validate(request, str(answer)))
        self.assertFalse(captcha.validate(request, str(answer)))

    def test_new_captcha_after_failed_attempt(self):
        """После неудачной попытки входа генерируется новый пример"""
        with mock.patch.object(captcha._rng, "randint", side_effect=[2, 3, 7, 1]), \
                mock.patch.object(captcha._rng, "choice", return_value="+"):
            self.client.get(reverse("login"))  # пример 2 + 3
            self.assertEqual(self.client.session[captcha.SESSION_ANSWER], 5)
            self.login_with_captcha("tester", "wrong-password", answer=5)
        self.assertEqual(self.client.session[captcha.SESSION_ANSWER], 8)  # пример 7 + 1
        self.assertFalse(self.is_logged_in())

    def test_captcha_field_cleared_after_error(self):
        """После ошибки поле капчи очищается"""
        answer = self.get_captcha_answer()
        response = self.login_with_captcha("tester", PASSWORD, answer=answer + 1)
        self.assertNotContains(response, f'value="{answer + 1}"')


# ---------------------------------------------------------------------------
# 2. РЕГИСТРАЦИЯ
# ---------------------------------------------------------------------------
class RegistrationTests(CaptchaHelpersMixin, TestCase):
    report_group = "Регистрация"

    def valid_data(self, **overrides):
        data = {
            "username": "newuser",
            "email": "new@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        data.update(overrides)
        return data

    def test_register_page_opens(self):
        """Страница регистрации открывается"""
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")

    def test_successful_registration(self):
        """Успешная регистрация создаёт пользователя и перенаправляет на вход"""
        response = self.client.post(reverse("register"), self.valid_data())
        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="newuser")
        self.assertEqual(user.email, "new@example.com")

    def test_password_is_hashed(self):
        """Пароль сохраняется в базе в зашифрованном виде"""
        self.client.post(reverse("register"), self.valid_data())
        user = User.objects.get(username="newuser")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_user_not_logged_in_after_registration(self):
        """После регистрации пользователь не входит автоматически (нужна капча)"""
        self.client.post(reverse("register"), self.valid_data())
        self.assertFalse(self.is_logged_in())

    def test_passwords_mismatch(self):
        """Несовпадающие пароли — регистрация отклонена"""
        response = self.client.post(reverse("register"), self.valid_data(password2="Other!Pass2024"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_duplicate_username(self):
        """Занятое имя пользователя — регистрация отклонена"""
        User.objects.create_user("newuser", "other@example.com", PASSWORD)
        response = self.client.post(reverse("register"), self.valid_data())
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(User.objects.filter(username="newuser").count(), 1)

    def test_duplicate_email(self):
        """Занятый email (без учёта регистра) — регистрация отклонена"""
        User.objects.create_user("someone", "new@example.com", PASSWORD)
        response = self.client.post(reverse("register"), self.valid_data(email="NEW@example.com"))
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_invalid_email(self):
        """Некорректный email — регистрация отклонена"""
        response = self.client.post(reverse("register"), self.valid_data(email="not-an-email"))
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_weak_password(self):
        """Слабый пароль (12345) — регистрация отклонена валидаторами Django"""
        response = self.client.post(
            reverse("register"), self.valid_data(password1="12345", password2="12345")
        )
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_empty_form(self):
        """Пустая форма — ошибки для всех обязательных полей"""
        response = self.client.post(reverse("register"), {})
        errors = response.context["form"].errors
        for field in ("username", "email", "password1", "password2"):
            self.assertIn(field, errors)
        self.assertEqual(User.objects.count(), 0)

    def test_registered_user_can_login_with_captcha(self):
        """Зарегистрированный пользователь может войти, решив капчу"""
        self.client.post(reverse("register"), self.valid_data())
        response = self.login_with_captcha("newuser", PASSWORD)
        self.assertRedirects(response, reverse("profile"))
        self.assertTrue(self.is_logged_in())

    def test_authenticated_user_redirected_from_register(self):
        """Авторизованного пользователя со страницы регистрации перенаправляет в кабинет"""
        user = User.objects.create_user("logged", "logged@example.com", PASSWORD)
        self.client.force_login(user)
        response = self.client.get(reverse("register"))
        self.assertRedirects(response, reverse("profile"))


# ---------------------------------------------------------------------------
# 3. АВТОРИЗАЦИЯ
# ---------------------------------------------------------------------------
class LoginTests(CaptchaHelpersMixin, TestCase):
    report_group = "Авторизация"

    def setUp(self):
        self.user = User.objects.create_user("ivan", "ivan@example.com", PASSWORD)

    def test_login_page_opens(self):
        """Страница входа открывается"""
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")

    def test_successful_login_with_captcha(self):
        """Верные логин, пароль и капча — вход выполнен, переход в личный кабинет"""
        response = self.login_with_captcha("ivan", PASSWORD)
        self.assertRedirects(response, reverse("profile"))
        self.assertTrue(self.is_logged_in())
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_wrong_password(self):
        """Неверный пароль (капча верная) — вход запрещён"""
        response = self.login_with_captcha("ivan", "WrongPass!111")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.is_logged_in())
        self.assertTrue(response.context["form"].non_field_errors())

    def test_nonexistent_user(self):
        """Несуществующий пользователь — вход запрещён"""
        response = self.login_with_captcha("nobody", PASSWORD)
        self.assertFalse(self.is_logged_in())
        self.assertTrue(response.context["form"].non_field_errors())

    def test_empty_credentials(self):
        """Пустые логин и пароль — ошибки валидации"""
        response = self.login_with_captcha("", "")
        errors = response.context["form"].errors
        self.assertIn("username", errors)
        self.assertIn("password", errors)
        self.assertFalse(self.is_logged_in())

    def test_inactive_user_denied(self):
        """Заблокированный (неактивный) пользователь не может войти"""
        self.user.is_active = False
        self.user.save()
        self.login_with_captcha("ivan", PASSWORD)
        self.assertFalse(self.is_logged_in())

    def test_last_login_updated(self):
        """После входа обновляется дата последнего входа"""
        self.assertIsNone(self.user.last_login)
        self.login_with_captcha("ivan", PASSWORD)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_redirect_to_next(self):
        """После входа выполняется переход на страницу из параметра next"""
        target = reverse("profile_edit")
        response = self.login_with_captcha("ivan", PASSWORD, url=f"{reverse('login')}?next={target}")
        self.assertRedirects(response, target)

    def test_unsafe_next_ignored(self):
        """Внешняя ссылка в next игнорируется (защита от open redirect)"""
        response = self.login_with_captcha(
            "ivan", PASSWORD, url=f"{reverse('login')}?next=http://evil.example.com/"
        )
        self.assertRedirects(response, reverse("profile"))

    def test_authenticated_user_redirected_from_login(self):
        """Авторизованного пользователя со страницы входа перенаправляет в кабинет"""
        self.client.force_login(self.user)
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("profile"))

    def test_logout(self):
        """Выход из системы завершает сессию и ведёт на страницу входа"""
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(self.is_logged_in())

    def test_logout_requires_post(self):
        """Выход по GET-запросу запрещён (защита от CSRF)"""
        self.client.force_login(self.user)
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.is_logged_in())


# ---------------------------------------------------------------------------
# 4. ЛИЧНЫЙ КАБИНЕТ
# ---------------------------------------------------------------------------
class ProfileTests(CaptchaHelpersMixin, TestCase):
    report_group = "Личный кабинет"

    def setUp(self):
        self.user = User.objects.create_user(
            "ivan", "ivan@example.com", PASSWORD, first_name="Иван", last_name="Петров"
        )
        self.other = User.objects.create_user("petr", "petr@example.com", PASSWORD)

    def test_anonymous_redirected_to_login(self):
        """Неавторизованного пользователя из кабинета перенаправляет на вход"""
        response = self.client.get(reverse("profile"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")

    def test_profile_shows_user_data(self):
        """В личном кабинете отображаются данные пользователя"""
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ivan@example.com")
        self.assertContains(response, "Иван")
        self.assertContains(response, "Петров")

    def test_profile_shows_only_own_data(self):
        """В кабинете не отображаются данные других пользователей"""
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertNotContains(response, "petr@example.com")

    def test_edit_page_opens(self):
        """Страница редактирования профиля открывается и заполнена текущими данными"""
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="ivan@example.com"')

    def test_edit_profile_success(self):
        """Изменение имени, фамилии и email сохраняется"""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile_edit"),
            {"first_name": "Сергей", "last_name": "Сидоров", "email": "sergey@example.com"},
        )
        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Сергей")
        self.assertEqual(self.user.last_name, "Сидоров")
        self.assertEqual(self.user.email, "sergey@example.com")

    def test_edit_invalid_email(self):
        """Некорректный email при редактировании — данные не сохраняются"""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile_edit"), {"first_name": "Иван", "last_name": "Петров", "email": "bad"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ivan@example.com")

    def test_edit_email_taken(self):
        """Email другого пользователя нельзя указать в своём профиле"""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile_edit"),
            {"first_name": "Иван", "last_name": "Петров", "email": "petr@example.com"},
        )
        self.assertIn("email", response.context["form"].errors)

    def test_edit_anonymous_redirected(self):
        """Редактирование профиля недоступно без авторизации"""
        response = self.client.get(reverse("profile_edit"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile_edit')}")

    def test_full_flow_register_login_profile(self):
        """Сквозной сценарий: регистрация → вход с капчей → личный кабинет"""
        self.client.post(
            reverse("register"),
            {"username": "anna", "email": "anna@example.com", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.login_with_captcha("anna", PASSWORD)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "anna@example.com")

    def test_profile_unavailable_after_logout(self):
        """После выхода личный кабинет недоступен"""
        self.login_with_captcha("ivan", PASSWORD)
        self.client.post(reverse("logout"))
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)

    def test_report_download_requires_login(self):
        """Скачивание отчёта о тестах доступно только авторизованным"""
        response = self.client.get(reverse("report_latest"))
        self.assertEqual(response.status_code, 302)

    def test_report_download(self):
        """Из личного кабинета можно скачать последний Word-отчёт"""
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "test_report_sample.docx").write_bytes(b"docx-content")
            with override_settings(REPORTS_DIR=tmp):
                self.client.force_login(self.user)
                response = self.client.get(reverse("report_latest"))
                self.assertEqual(response.status_code, 200)
                self.assertIn("attachment", response["Content-Disposition"])
                self.assertEqual(b"".join(response.streaming_content), b"docx-content")
                response.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_report_download_no_reports(self):
        """Если отчётов нет — возвращается 404"""
        tmp = Path(tempfile.mkdtemp())
        try:
            with override_settings(REPORTS_DIR=tmp):
                self.client.force_login(self.user)
                response = self.client.get(reverse("report_latest"))
                self.assertEqual(response.status_code, 404)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
