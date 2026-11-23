
import random

SESSION_ANSWER = "captcha_answer"
SESSION_QUESTION = "captcha_question"

# Отдельный генератор, чтобы в тестах можно было подменить только его.
_rng = random.Random()


def generate(request):
    """Создаёт новый пример, сохраняет ответ в сессии и возвращает текст примера."""
    a = _rng.randint(1, 9)
    b = _rng.randint(1, 9)
    op = _rng.choice(["+", "-"])
    if op == "-" and a < b:
        a, b = b, a
    answer = a + b if op == "+" else a - b
    question = f"{a} {op} {b} = ?"
    request.session[SESSION_ANSWER] = answer
    request.session[SESSION_QUESTION] = question
    return question


def invalidate(request):
    """Удаляет текущую капчу из сессии."""
    request.session.pop(SESSION_ANSWER, None)
    request.session.pop(SESSION_QUESTION, None)


def validate(request, value):
    """
    Проверяет ответ пользователя. Капча одноразовая — после проверки
    (успешной или нет) ответ из сессии удаляется.
    """
    expected = request.session.pop(SESSION_ANSWER, None)
    request.session.pop(SESSION_QUESTION, None)
    if expected is None or value is None:
        return False
    value = str(value).strip()
    if not value.isdigit():
        return False
    return int(value) == int(expected)


def render_svg(question):

    width, height = 180, 56
    rnd = random.Random()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" rx="6" fill="#eef2f7"/>',
    ]
    # Шумовые линии
    for _ in range(6):
        x1, y1 = rnd.randint(0, width), rnd.randint(0, height)
        x2, y2 = rnd.randint(0, width), rnd.randint(0, height)
        color = f"#{rnd.randint(0x77, 0xCC):02x}{rnd.randint(0x77, 0xCC):02x}{rnd.randint(0x77, 0xCC):02x}"
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.5"/>'
        )
    # Символы примера, каждый со своим поворотом и цветом
    x = 14
    for ch in question:
        if ch == " ":
            x += 8
            continue
        angle = rnd.randint(-25, 25)
        y = rnd.randint(34, 42)
        color = f"#{rnd.randint(0x10, 0x60):02x}{rnd.randint(0x10, 0x60):02x}{rnd.randint(0x40, 0x90):02x}"
        parts.append(
            f'<text x="{x}" y="{y}" font-family="Courier New, monospace" font-size="28" '
            f'font-weight="bold" fill="{color}" transform="rotate({angle} {x} {y})">{ch}</text>'
        )
        x += 20
    # Шумовые точки
    for _ in range(40):
        cx, cy = rnd.randint(0, width), rnd.randint(0, height)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="1.2" fill="#8899aa"/>')
    parts.append("</svg>")
    return "".join(parts)
