"""
Формирование отчёта о тестировании в формате Word (.docx)
с помощью библиотеки python-docx.
"""
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

STATUS_LABELS = {
    "passed": ("Пройден", "D9F2DF", RGBColor(0x1B, 0x6B, 0x33)),
    "failed": ("Не пройден", "F8D7DA", RGBColor(0x9B, 0x1C, 0x1C)),
    "error": ("Ошибка", "F8D7DA", RGBColor(0x9B, 0x1C, 0x1C)),
    "skipped": ("Пропущен", "E5E7EB", RGBColor(0x4B, 0x55, 0x63)),
}
HEADER_FILL = "1F3A5F"


def _shade(cell, hex_fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def _set_cell(cell, text, bold=False, color=None, size=10, align=None):
    cell.text = ""
    para = cell.paragraphs[0]
    run = para.add_run(str(text))
    run.bold = bold
    run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    if align is not None:
        para.alignment = align


def _header_row(table, titles):
    for cell, title in zip(table.rows[0].cells, titles):
        _set_cell(cell, title, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF), align=WD_ALIGN_PARAGRAPH.CENTER)
        _shade(cell, HEADER_FILL)
    # Повторять шапку таблицы на каждой странице
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _set_widths(table, widths_cm):
    table.autofit = False
    for col, w in zip(table.columns, widths_cm):
        col.width = Cm(w)
    for row in table.rows:
        for cell, w in zip(row.cells, widths_cm):
            cell.width = Cm(w)


def _key_value_table(doc, rows):
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for key, value in rows:
        cells = table.add_row().cells
        _set_cell(cells[0], key, bold=True, size=11)
        _shade(cells[0], "EEF2F7")
        _set_cell(cells[1], value, size=11)
    _set_widths(table, [6, 11])
    return table


def build_report(records, output_dir, meta):
    """Создаёт .docx-отчёт и возвращает путь к файлу."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = meta.get("started_at") or datetime.now()

    total = len(records)
    counts = {key: sum(1 for r in records if r["status"] == key) for key in STATUS_LABELS}
    success_rate = (counts["passed"] / total * 100) if total else 0.0

    doc = Document()
    section = doc.sections[0]
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(1.5)
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")

    title = doc.add_heading("Отчёт о результатах автоматизированного тестирования", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(
        "Модули: регистрация, авторизация с капчей, личный кабинет"
    ).italic = True

    # 1. Общие сведения
    doc.add_heading("1. Общие сведения", level=1)
    _key_value_table(doc, [
        ("Проект", meta.get("project", "Django-проект")),
        ("Дата и время запуска", started_at.strftime("%d.%m.%Y %H:%M:%S")),
        ("Длительность прогона", f"{meta.get('duration', 0):.2f} с"),
        ("Фреймворк тестирования", "django.test (unittest), тест-клиент Django"),
        ("Версия Django", meta.get("django", "—")),
        ("Версия Python", meta.get("python", "—")),
        ("Операционная система", meta.get("os", "—")),
        ("База данных", "Тестовая SQLite (создаётся и удаляется автоматически)"),
    ])

    # 2. Итоги
    doc.add_heading("2. Итоговые результаты", level=1)
    _key_value_table(doc, [
        ("Всего тестов", total),
        ("Пройдено", counts["passed"]),
        ("Не пройдено", counts["failed"]),
        ("Ошибки выполнения", counts["error"]),
        ("Пропущено", counts["skipped"]),
        ("Процент успешных", f"{success_rate:.1f} %"),
    ])

    # 3. По модулям
    doc.add_heading("3. Результаты по модулям", level=1)
    groups = OrderedDict()
    for r in records:
        g = groups.setdefault(r["group"], {"total": 0, "passed": 0, "bad": 0, "time": 0.0})
        g["total"] += 1
        g["time"] += r["duration"]
        if r["status"] == "passed":
            g["passed"] += 1
        elif r["status"] in ("failed", "error"):
            g["bad"] += 1
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _header_row(table, ["Модуль", "Всего", "Пройдено", "Не пройдено", "Время, с"])
    for name, g in groups.items():
        cells = table.add_row().cells
        _set_cell(cells[0], name, bold=True, size=11)
        for cell, value in zip(cells[1:], [g["total"], g["passed"], g["bad"], f"{g['time']:.3f}"]):
            _set_cell(cell, value, size=11, align=WD_ALIGN_PARAGRAPH.CENTER)
        if g["bad"]:
            _shade(cells[3], STATUS_LABELS["failed"][1])
    _set_widths(table, [5.5, 2.5, 3, 3, 3])

    # 4. Подробно
    doc.add_heading("4. Подробные результаты тестов", level=1)
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    _header_row(table, ["№", "Модуль", "Тест-кейс", "Результат", "Время, с"])
    for i, r in enumerate(records, 1):
        label, fill, color = STATUS_LABELS.get(r["status"], STATUS_LABELS["error"])
        cells = table.add_row().cells
        _set_cell(cells[0], i, align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_cell(cells[1], r["group"])
        # описание + имя метода мелким шрифтом
        cells[2].text = ""
        p = cells[2].paragraphs[0]
        run = p.add_run(r["description"] or r["method"])
        run.font.size = Pt(10)
        p2 = cells[2].add_paragraph()
        run2 = p2.add_run(r["method"])
        run2.font.size = Pt(8)
        run2.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        _set_cell(cells[3], label, bold=True, color=color, align=WD_ALIGN_PARAGRAPH.CENTER)
        _shade(cells[3], fill)
        _set_cell(cells[4], f"{r['duration']:.3f}", align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_widths(table, [1, 3, 8.5, 2.5, 2])

    # 5. Ошибки
    problems = [r for r in records if r["status"] in ("failed", "error")]
    if problems:
        doc.add_heading("5. Описание обнаруженных ошибок", level=1)
        for r in problems:
            doc.add_paragraph(f"{r['group']}: {r['description'] or r['method']}", style="List Number")
            p = doc.add_paragraph()
            run = p.add_run(r["details"].strip()[-3000:])
            run.font.name = "Consolas"
            run.font.size = Pt(8)
    concl_num = 6 if problems else 5

    # Заключение
    doc.add_heading(f"{concl_num}. Заключение", level=1)
    if total == 0:
        text = "Тесты не были выполнены."
    elif not problems:
        text = (
            f"Все {total} автоматизированных тестов пройдены успешно. "
            "Функции регистрации, авторизации с проверкой капчи и личного кабинета "
            "работают в соответствии с требованиями."
        )
    else:
        text = (
            f"Из {total} тестов успешно пройдено {counts['passed']}, "
            f"обнаружено проблем: {len(problems)}. Требуется исправление ошибок, "
            "указанных в разделе 5, и повторный прогон тестов."
        )
    doc.add_paragraph(text)

    filename = f"test_report_{started_at.strftime('%Y%m%d_%H%M%S')}.docx"
    path = output_dir / filename
    doc.save(path)
    return path
