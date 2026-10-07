# -*- coding: utf-8 -*-
"""تحليل نص التقرير بـ Gemini أو محلياً لملء الغلاف والملاحظات."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from report_engine import today_date_str


def get_gemini_api_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if key:
        return key
    try:
        import auth_store

        auth_store.init_db()
        with auth_store.db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='gemini_api_key'"
            ).fetchone()
            return (row["value"] if row else "").strip()
    except Exception:
        return ""


def set_gemini_api_key(key: str) -> None:
    import auth_store

    auth_store.set_gemini_api_key(key)


def parse_report_text_local(raw_text: str) -> dict[str, Any]:
    """محلل محلي بسيط بدون Gemini للنصوص المنظمة."""
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    school = ""
    ministry_no = ""
    engineer = ""
    date = ""
    title = ""
    observations: list[str] = []

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    label_patterns = [
        (r"^(?:عنوان(?:\s*التقرير)?|title)\s*[:：]\s*(.+)$", "title"),
        (r"^(?:اسم\s*المدرسة|المدرسة)\s*[:：]\s*(.+)$", "school"),
        (r"^(?:الرقم\s*الوزاري|رقم\s*وزاري)\s*[:：]\s*(.+)$", "ministry_no"),
        (r"^(?:المشرف|اسم\s*المشرف|المهندس|اسم\s*المهندس|المعد)\s*[/:]?\s*[:：]?\s*(.*)$", "engineer"),
        (r"^(?:التاريخ)\s*[:：]\s*(.+)$", "date"),
    ]

    for ln in lines:
        matched = False
        for pat, key in label_patterns:
            m = re.match(pat, ln, flags=re.IGNORECASE)
            if not m:
                continue
            val = (m.group(1) or "").strip(" .:-/")
            if key == "title":
                title = val
            elif key == "school":
                school = val
            elif key == "ministry_no":
                ministry_no = val
            elif key == "engineer":
                engineer = val
            elif key == "date":
                date = val
            matched = True
            break
        if matched:
            continue
        # أسطر الملاحظات / أو تعداد
        clean = re.sub(r"^[\-•●▪►\d\)\(\.]+\s*", "", ln).strip()
        if clean and clean not in {"الملاحظات", "إجمالي الملاحظات", "ملاحظات"}:
            # تجاهل أسطر قصيرة جداً إن كانت فواصل
            if len(clean) >= 2:
                observations.append(clean)

    if not date:
        date = today_date_str()

    return {
        "title": title or "التقرير الفني لحالة المبنى",
        "school": school,
        "ministry_no": ministry_no,
        "engineer": engineer,
        "date": date,
        "observations": observations,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def parse_report_text_gemini(raw_text: str, api_key: str | None = None) -> dict[str, Any]:
    api_key = (api_key or get_gemini_api_key()).strip()
    if not api_key:
        raise ValueError("لم يتم ضبط مفتاح Gemini API")

    today = today_date_str()
    prompt = f"""أنت مساعد يستخرج بيانات تقرير فني مدرسي عربي.
أرجع JSON فقط بدون شرح، بالشكل:
{{
  "title": "التقرير الفني لحالة المبنى",
  "school": "",
  "ministry_no": "",
  "engineer": "",
  "date": "",
  "observations": ["...", "..."]
}}
القواعد:
- engineer = اسم المشرف أو المهندس إن وُجد.
- observations = قائمة الملاحظات كاملة، كل ملاحظة عنصر مستقل (ستظهر كنقطة/رصاصة في الشريحة الثانية).
- لا تدمج عدة ملاحظات في عنصر واحد.
- إذا لم يوجد تاريخ استخدم "{today}".
- لا تختصر الملاحظات.

النص:
{raw_text}
"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"خطأ Gemini ({e.code}): {detail[:300]}") from e

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("استجابة Gemini غير متوقعة") from e

    parsed = _extract_json_object(text)
    local = parse_report_text_local(raw_text)

    cover = {
        "title": (parsed.get("title") or local["title"] or "التقرير الفني لحالة المبنى").strip(),
        "school": (parsed.get("school") or local["school"] or "").strip(),
        "ministry_no": (parsed.get("ministry_no") or local["ministry_no"] or "").strip(),
        "engineer": (parsed.get("engineer") or local["engineer"] or "").strip(),
        "date": (parsed.get("date") or local["date"] or today).strip(),
    }
    obs = parsed.get("observations")
    if not isinstance(obs, list) or not obs:
        obs = local["observations"]
    observations = [str(x).strip() for x in obs if str(x).strip()]

    return {"cover": cover, "observations": observations, "source": "gemini"}


def parse_report_text(raw_text: str, prefer_gemini: bool = True) -> dict[str, Any]:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("النص فارغ")

    if prefer_gemini and get_gemini_api_key():
        try:
            return parse_report_text_gemini(raw_text)
        except Exception:
            # احتياطي محلي إذا فشل Gemini
            data = parse_report_text_local(raw_text)
            return {
                "cover": {
                    "title": data["title"],
                    "school": data["school"],
                    "ministry_no": data["ministry_no"],
                    "engineer": data["engineer"],
                    "date": data["date"] or today_date_str(),
                },
                "observations": data["observations"],
                "source": "local_fallback",
            }

    data = parse_report_text_local(raw_text)
    return {
        "cover": {
            "title": data["title"],
            "school": data["school"],
            "ministry_no": data["ministry_no"],
            "engineer": data["engineer"],
            "date": data["date"] or today_date_str(),
        },
        "observations": data["observations"],
        "source": "local",
    }
