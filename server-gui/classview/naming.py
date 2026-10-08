"""Разбор имён хостов вида <тип><школа>-<корпус>-<кабинет>-<номер>.

Тип: p — панель, n — ноутбук, m — моноблок. Номер школы задаётся в настройках
(school_id); при пустом school_id принимается любой числовой префикс школы.
"""
import re


def _regex(school_id: str = ""):
    school = re.escape(school_id) if school_id else r"\d+"
    return re.compile(rf"^([pnm]){school}-(\d+)-([^-]+)-(\d+)$", re.IGNORECASE)


def parse_hostname(hostname: str, school_id: str = ""):
    """Возвращает (тип, корпус, кабинет, номер) или None.

    school_id ограничивает разбор конкретной школой; пустой — принимает любую.
    """
    m = _regex(school_id).match(hostname.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2), m.group(3), m.group(4)


def is_panel(hostname: str, school_id: str = "") -> bool:
    p = parse_hostname(hostname, school_id)
    return bool(p) and p[0] == "p"


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s or "")]
