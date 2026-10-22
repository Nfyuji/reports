# -*- coding: utf-8 -*-
"""قائمة المدارس: رقم القائمة → الاسم + الرقم الوزاري."""

from __future__ import annotations

import re

# الرقم الوزاري للمدرستين 2 و 4 كما ورد (كانت عليهما علامة ولم تتضح خانة إضافية).
SCHOOLS: list[dict[str, str]] = [
    {"name": "المتوسطة الخامسة والعشرون بخميس مشيط", "ministry": "63637"},
    {"name": "الروضة العاشرة بالخميس", "ministry": "69053"},
    {"name": "ابتدائية الرصراص الثانية بالخميس", "ministry": "63557"},
    {"name": "الابتدائية الثالثة والخمسون بالخميس", "ministry": "16251"},
    {"name": "المتوسطة الثامنة عشر بخميس مشيط", "ministry": "63198"},
    {"name": "الثانوية الخامسة عشر بخميس مشيط - مسارات", "ministry": "3963550"},
    {"name": "الروضة التاسعة بالخميس + الطفولة المبكرة بالروضة التاسعة بخميس مشيط", "ministry": "69023"},
    {"name": "الابتدائية الخامسة والأربعون بالخميس", "ministry": "63656"},
    {"name": "ابتدائية الوقية", "ministry": "62634"},
    {"name": "ابتدائية الفاروق", "ministry": "61695"},
    {"name": "ابتدائية زيد بن حارثة للطفولة المبكرة بالخميس + الروضة الملحقة", "ministry": "162719"},
    {"name": "ثانوية عبدالعزيز الخويطر - مسارات", "ministry": "162072"},
    {"name": "متوسطة عمرو بن العاص + ابتدائية تحفيظ الندوة", "ministry": "61392"},
    {"name": "ابتدائية الرصراص الأولى بالخميس", "ministry": "62914"},
    {"name": "متوسطة وثانوية الوقية بخميس مشيط", "ministry": "63163"},
    {"name": "متوسطة الهرير + ابتدائية العباس بن عبدالمطلب", "ministry": "61385"},
    {"name": "متوسطة وثانوية الهرير بخميس مشيط", "ministry": "63152"},
    {"name": "ثانوية البيقفي - مسارات", "ministry": "161002"},
    {"name": "ابتدائية الهرير الأولى", "ministry": "62699"},
    {"name": "الابتدائية السادسة والعشرون بالخميس", "ministry": "62820"},
    {"name": "ابتدائية عدي بن حاتم", "ministry": "61216"},
]

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def school_list_text() -> str:
    lines = ["أرسل *رقم المدرسة* فقط من القائمة:"]
    for i, s in enumerate(SCHOOLS, start=1):
        lines.append(f"{i}. {s['name']}")
    return "\n".join(lines)


def lookup_school_number(text: str) -> dict[str, str] | None:
    """يعيد المدرسة إن كان النص رقماً من 1 إلى آخر القائمة."""
    raw = (text or "").strip().translate(_AR_DIGITS)
    raw = raw.replace("#", "").strip()
    raw = re.sub(r"^(?:رقم|مدرسه|المدرسه)\s*", "", raw).strip()
    if not re.fullmatch(r"\d{1,2}", raw):
        return None
    n = int(raw)
    if 1 <= n <= len(SCHOOLS):
        item = dict(SCHOOLS[n - 1])
        item["no"] = str(n)
        return item
    return None
