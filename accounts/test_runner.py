
import platform
import time
import unittest
from datetime import datetime

import django
from django.conf import settings
from django.test.runner import DiscoverRunner

from .word_report import build_report


class RecordingTestResult(unittest.TextTestResult):
    """Результат прогона, который запоминает каждый тест для отчёта."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._started = {}

    def startTest(self, test):
        self._started[test.id()] = time.perf_counter()
        super().startTest(test)

    def _record(self, test, status, details="", parent=None):
        start = self._started.get((parent or test).id(), time.perf_counter())
        owner = parent or test
        method = getattr(owner, "_testMethodName", str(owner))
        if parent is not None:
            method = f"{method} {test._subDescription()}"
        self.records.append({
            "id": test.id(),
            "group": getattr(owner, "report_group", owner.__class__.__name__),
            "method": method,
            "description": owner.shortDescription() or "",
            "status": status,
            "duration": time.perf_counter() - start,
            "details": details,
        })

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "passed", "Ожидаемая ошибка (expectedFailure)")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failed", "Неожиданный успех (unexpected success)")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            failed = issubclass(err[0], test.failureException)
            self._record(subtest, "failed" if failed else "error",
                         self._exc_info_to_string(err, test), parent=test)


class WordReportTestRunner(DiscoverRunner):
    def get_resultclass(self):
        return RecordingTestResult

    def run_suite(self, suite, **kwargs):
        started_at = datetime.now()
        t0 = time.perf_counter()
        result = super().run_suite(suite, **kwargs)
        meta = {
            "project": "CaptchaLab (Django)",
            "started_at": started_at,
            "duration": time.perf_counter() - t0,
            "python": platform.python_version(),
            "django": django.get_version(),
            "os": platform.platform(),
        }
        try:
            path = build_report(getattr(result, "records", []), settings.REPORTS_DIR, meta)
            print(f"\nОтчёт о тестировании сохранён в Word: {path}")
        except Exception as exc:  # отчёт не должен ломать сам прогон тестов
            print(f"\nНе удалось сохранить Word-отчёт: {exc}")
        return result
