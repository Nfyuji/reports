# -*- coding: utf-8 -*-
"""محرك قراءة/تعبئة تقرير الإكسل اليومي (O&M / HVAC / CLEANING)."""

from __future__ import annotations

import io
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage

BASE = Path(__file__).resolve().parent

# مفاتيح آمنة للويب (بدون &) ← اسم ورقة الإكسل الفعلي
# O&M كان يكسر HTML/FormData بسبب علامة &
SHEET_META = {
    "OM": {
        "key": "OM",
        "sheet_name": "O&M",
        "ar": "صيانة",
        "en": "O&M",
        "color": "green",
        "photo_label": "صور الصيانة",
        "order": 1,
    },
    "HVAC": {
        "key": "HVAC",
        "sheet_name": "HVAC",
        "ar": "تكييف",
        "en": "HVAC",
        "color": "red",
        "photo_label": "صور التكييف",
        "order": 2,
    },
    "CLEANING": {
        "key": "CLEANING",
        "sheet_name": "CLEANING",
        "ar": "نظافة",
        "en": "CLEANING",
        "color": "blue",
        "photo_label": "صور نظافة المبنى",
        "order": 3,
    },
}

# توافق عكسي إن وصل مفتاح قديم
SHEET_ALIASES = {
    "O&M": "OM",
    "OM": "OM",
    "HVAC": "HVAC",
    "CLEANING": "CLEANING",
}


def normalize_sheet_key(key: str) -> str:
    return SHEET_ALIASES.get((key or "").strip(), (key or "").strip())


def excel_sheet_name(key: str) -> str:
    k = normalize_sheet_key(key)
    meta = SHEET_META.get(k)
    return meta["sheet_name"] if meta else key

MONTHS = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}

SKIP_LABELS = {
    "البند",
    "*",
    "المتطلبات الاساسية",
    "Basic Requirements",
}


def master_daily_path() -> Path | None:
    import auth_store

    auth_store.ensure_dirs()
    for name in ("daily_report.xlsx", "قالب_التقرير_اليومي.xlsx"):
        p = auth_store.MASTER_DIR / name
        if p.exists():
            return p
    local = BASE / "master_templates" / "daily_report.xlsx"
    if local.exists():
        return local
    # أي xlsx في الجذر كاحتياطي
    for p in BASE.glob("*.xlsx"):
        return p
    return None


def user_daily_path(user) -> Path:
    path = user.workspace / "daily_report.xlsx"
    if not path.exists():
        master = master_daily_path()
        if not master:
            raise FileNotFoundError("لا يوجد قالب إكسل يومي. ارفعه من لوحة الإدارة.")
        user.workspace.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master, path)
    return path


def user_daily_state_path(user) -> Path:
    return user.workspace / "daily_state.json"


def today_parts() -> tuple[int, str, int]:
    now = datetime.now()
    return now.year, MONTHS[now.month], now.day


def _is_section_header(text: str) -> bool:
    t = (text or "").strip()
    if not t or t in SKIP_LABELS:
        return True
    if t.startswith("المتطلبات"):
        return True
    # عناوين أقسام طويلة بدون جملة بند عادية
    if "STAFF" in t or "Building" in t or "Cleaning Practices" in t:
        return True
    if t.endswith(":") or t.endswith("؟") is False and len(t) < 4:
        return False
    return False


def _looks_like_item(text: str) -> bool:
    t = (text or "").strip()
    if not t or t in SKIP_LABELS:
        return False
    if t in {"اسم المدرسة", "الرقم الوزاري"}:
        return False
    # عناوين أقسام غالباً أقصر أو تنتهي بدون فعل فحص
    if re.match(r"^\d+$", t):
        return False
    return len(t) >= 6


def _is_english_only(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    arabic = sum(1 for ch in t if "\u0600" <= ch <= "\u06FF")
    return arabic == 0


def _is_checklist_item_text(text: str) -> bool:
    t = (text or "").strip()
    if not _looks_like_item(t):
        return False
    if _is_english_only(t):
        return False
    low = t.lower()
    if "specifications" in low or "professional photos" in low or "photo report" in low:
        return False
    if "متوفر" in t and len(t) < 45:
        return False
    if t.startswith(("تكييف ", "العاملين", "نظافة المرفق", "الأنظمة", "أنظمة", "نظام ", "الملاحظات العامة")):
        # عناوين أقسام — ليست بنوداً قابلة للتأشير وحدها
        if not t.startswith(("فحص", "تنظيف", "هل", "اختبار", "إختبار")):
            return False
    return True


def extract_sheet_items(ws) -> list[dict[str, Any]]:
    """يستخرج بنود القائمة من عمودي اليسار (A/E) واليمين (M/Q)."""
    items: list[dict[str, Any]] = []
    max_r = min(ws.max_row or 1, 220)

    for r in range(12, max_r + 1):
        a = ws[f"A{r}"].value
        e = ws[f"E{r}"].value
        m = ws[f"M{r}"].value
        q = ws[f"Q{r}"].value
        i_en = ws[f"I{r}"].value

        if str(a or "").strip() == "البند" or str(m or "").strip() == "البند":
            continue

        # عنوان قسم مرقّم في L
        if isinstance(ws[f"L{r}"].value, (int, float)):
            continue

        # يسار
        if isinstance(a, str) and _is_checklist_item_text(a):
            f_val = ws[f"F{r}"].value
            h_val = ws[f"H{r}"].value
            likely = (
                isinstance(i_en, str)
                or e == "تم Done"
                or f_val in ("P", "O")
                or h_val in ("P", "O")
                or a.strip().startswith(
                    (
                        "فحص",
                        "تنظيف",
                        "إختبار",
                        "اختبار",
                        "هل",
                        "استبدال",
                        "مراجعة",
                        "تشغيل",
                        "التحقق",
                        "التأكد",
                        "تنفي",
                        "الاست",
                        "جميع",
                        "السلوك",
                        "ممارسات",
                        "عدم",
                        "لا يوجد",
                    )
                )
            )
            if likely:
                done = e == "تم Done" or f_val == "P" or h_val == "P"
                items.append(
                    {
                        "id": f"L{r}",
                        "side": "left",
                        "row": r,
                        "done_cell": f"E{r}",
                        "text": a.strip(),
                        "done": bool(done),
                    }
                )

        # يمين
        if isinstance(m, str) and _is_checklist_item_text(m):
            r_val = ws[f"R{r}"].value
            done = q == "تم Done" or r_val == "P"
            items.append(
                {
                    "id": f"R{r}",
                    "side": "right",
                    "row": r,
                    "done_cell": f"Q{r}",
                    "text": m.strip(),
                    "done": bool(done),
                }
            )

    return items


def read_header(ws) -> dict[str, Any]:
    year = ws["J7"].value
    month = ws["L7"].value
    day = ws["M7"].value
    return {
        "school": (ws["C3"].value or "").strip() if isinstance(ws["C3"].value, str) else (ws["C3"].value or ""),
        "ministry_no": (ws["C4"].value or "") if ws["C4"].value is not None else "",
        "group_no": (ws["I4"].value or "") if ws["I4"].value is not None else "",
        "provider": (ws["C5"].value or "").strip() if isinstance(ws["C5"].value, str) else (ws["C5"].value or ""),
        "engineer": (ws["C6"].value or "").strip() if isinstance(ws["C6"].value, str) else (ws["C6"].value or ""),
        "year": year,
        "month": month,
        "day": day,
    }


def load_daily_structure(xlsx_path: Path) -> dict[str, Any]:
    wb = load_workbook(xlsx_path, data_only=False)
    sheets = []
    header = {}
    for key, meta in SHEET_META.items():
        sheet_name = meta["sheet_name"]
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        if not header:
            header = read_header(ws)
        sheets.append(
            {
                **meta,
                "items": extract_sheet_items(ws),
            }
        )
    sheets.sort(key=lambda s: s["order"])
    if not header.get("year"):
        y, m, d = today_parts()
        header.update({"year": y, "month": m, "day": d})
    return {"header": header, "sheets": sheets}


def _coord_row_col(coord: str) -> tuple[int, int]:
    from openpyxl.utils.cell import coordinate_to_tuple

    # (row, col)
    return coordinate_to_tuple(coord)


def _unmerge_at(ws, coord: str) -> None:
    """يفك أي دمج يغطي الخلية حتى تصبح قابلة للكتابة."""
    row, col = _coord_row_col(coord)
    doomed = []
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            doomed.append(str(rng))
    for ref in doomed:
        try:
            ws.unmerge_cells(ref)
        except Exception:
            pass


def _set_cell_value(ws, coord: str, value) -> None:
    """كتابة آمنة حتى لو الخلية ضمن دمج."""
    from openpyxl.cell.cell import MergedCell

    row, col = _coord_row_col(coord)
    # إن كانت ضمن دمج: اكتب في أول خلية ثم أعد الدمج إن لزم — الأبسط فك الدمج
    _unmerge_at(ws, coord)
    cell = ws.cell(row=row, column=col)
    if isinstance(cell, MergedCell):
        # محاولة أخيرة على زاوية أي دمج متبقٍ
        _unmerge_at(ws, coord)
        cell = ws.cell(row=row, column=col)
    if isinstance(cell, MergedCell):
        return
    try:
        cell.value = value
    except AttributeError:
        return


def _set_done(ws, cell: str, done: bool) -> None:
    """تعليم البند تم / إلغاء — يكتب في عمود Done."""
    try:
        _set_cell_value(ws, cell, "تم Done" if done else None)
        if cell.startswith("E"):
            r = int(re.sub(r"\D", "", cell) or "0")
            if r and done:
                _set_cell_value(ws, f"F{r}", None)
                _set_cell_value(ws, f"H{r}", None)
        if cell.startswith("Q"):
            r = int(re.sub(r"\D", "", cell) or "0")
            if r and done:
                _set_cell_value(ws, f"R{r}", None)
    except Exception:
        # لا تُسقط الحفظ كله بسبب بند واحد
        return


def _write_header(ws, header: dict[str, Any]) -> None:
    school = (header.get("school") or "").strip()
    ministry = header.get("ministry_no")
    ministry = "" if ministry is None else str(ministry).strip()
    group = header.get("group_no")
    group = "" if group is None else str(group).strip()
    provider = (header.get("provider") or "").strip()
    engineer = (header.get("engineer") or "").strip()

    y, m, d = today_parts()
    year = header.get("year") or y
    month = header.get("month") or m
    day = header.get("day") or d
    if isinstance(month, int):
        month = MONTHS.get(month, m)

    _set_cell_value(ws, "C3", school)
    _set_cell_value(ws, "C4", ministry)
    _set_cell_value(ws, "I4", group)
    _set_cell_value(ws, "C5", provider)
    _set_cell_value(ws, "C6", engineer)
    _set_cell_value(ws, "J7", int(year) if str(year).isdigit() else year)
    _set_cell_value(ws, "L7", str(month).upper()[:3])
    try:
        _set_cell_value(ws, "M7", int(day))
    except (TypeError, ValueError):
        _set_cell_value(ws, "M7", day)


def _prepare_image(blob: bytes, max_side: int = 900, box: tuple[int, int] | None = None) -> io.BytesIO:
    """يجهّز الصورة؛ إن مُرّر box=(w,h) تُناسب المربع مثل القالب (cover داخل الإطار)."""
    im = PILImage.open(io.BytesIO(blob))
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")
    if box:
        tw, th = max(40, box[0]), max(40, box[1])
        # غطِّ المربع مع قص بسيط من الوسط (مشابه لإدراج صورة في إكسل)
        src_ratio = im.width / im.height
        dst_ratio = tw / th
        if src_ratio > dst_ratio:
            new_h = th
            new_w = int(th * src_ratio)
        else:
            new_w = tw
            new_h = int(tw / src_ratio)
        im = im.resize((max(1, new_w), max(1, new_h)), PILImage.Resampling.LANCZOS)
        left = max(0, (im.width - tw) // 2)
        top = max(0, (im.height - th) // 2)
        im = im.crop((left, top, left + tw, top + th))
    else:
        im.thumbnail((max_side, max_side), PILImage.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    buf.seek(0)
    return buf


def _merge_size_px(ws, rng) -> tuple[int, int]:
    """عرض وارتفاع مربع الدمج بالبكسل (تقريب إكسل)."""
    width_px = 0
    for c in range(rng.min_col, rng.max_col + 1):
        letter = get_column_letter(c)
        w = ws.column_dimensions[letter].width
        width_px += int(float(w or 8.43) * 7 + 5)
    height_px = 0
    for r in range(rng.min_row, rng.max_row + 1):
        h = ws.row_dimensions[r].height
        height_px += int(float(h or 15) * 96 / 72)
    return max(80, width_px - 8), max(60, height_px - 8)


def _slot_sort_key(rng) -> tuple[int, int]:
    return (rng.min_row, rng.min_col)


def _is_photo_slot_merge(rng) -> bool:
    """مربع صورة في القالب: أعمدة B أو J أو Q بعرض/ارتفاع مناسب."""
    if rng.min_col not in (2, 10, 17):  # B, J, Q
        return False
    if (rng.max_col - rng.min_col) < 4:
        return False
    if (rng.max_row - rng.min_row) < 3:
        return False
    return True


def _slot_priority(val) -> int:
    """ترتيب التعبئة: #VALUE! أولاً ثم فارغ ثم إلزامي ثم اختياري."""
    if val is None or str(val).strip() == "":
        return 1
    s = str(val).strip().upper()
    if s in {"#VALUE!", "#VALUE"}:
        return 0
    if "MANDATORY" in s or "إلزامي" in str(val):
        return 2
    if "OPTIONAL" in s or "إختياري" in str(val) or "اختياري" in str(val):
        return 3
    return 9


def _find_value_photo_slots(ws) -> list:
    """
    مربعات الصور كما في قالب التقرير اليومي:
    B##:I## / J##:P## / Q##:X## بدءاً من صفوف #VALUE!
    ثم الفارغ / إلزامي / اختياري جنب بعضها.
    """
    candidates = [rng for rng in ws.merged_cells.ranges if _is_photo_slot_merge(rng)]
    if not candidates:
        return []

    # ابدأ من أول صف فيه #VALUE! (منطقة التقرير المصور)
    value_rows = [
        rng.min_row
        for rng in candidates
        if str(ws.cell(rng.min_row, rng.min_col).value or "").strip().upper()
        in {"#VALUE!", "#VALUE"}
    ]
    if value_rows:
        start_row = min(value_rows)
    else:
        # بعد الحفظ السابق تُمسح #VALUE! — ابدأ من أصغر صف مربعات تحت 50
        below = [rng.min_row for rng in candidates if rng.min_row >= 50]
        start_row = min(below) if below else 50

    usable = []
    for rng in candidates:
        if rng.min_row < start_row:
            continue
        val = ws.cell(rng.min_row, rng.min_col).value
        pr = _slot_priority(val)
        if pr >= 9:
            continue
        usable.append((pr, rng.min_row, rng.min_col, rng))

    # مهم: بعد مسح #VALUE! رتّب بالموقع (صف ثم عمود) حتى تبقى B→J→Q ثم الصف التالي
    usable.sort(key=lambda x: (x[1], x[2], x[0]))
    return [x[3] for x in usable]


def _photo_col_groups(slots: list) -> list[tuple[int, int]]:
    """مجموعات الأعمدة الثلاث من القالب (B:I / J:P / Q:X)."""
    if not slots:
        return [(2, 9), (10, 16), (17, 24)]
    # خذ صفاً فيه 3 مربعات إن أمكن
    by_row: dict[int, list] = {}
    for s in slots:
        by_row.setdefault(s.min_row, []).append(s)
    for _r, group in sorted(by_row.items()):
        if len(group) >= 3:
            group = sorted(group, key=lambda x: x.min_col)
            return [(g.min_col, g.max_col) for g in group[:3]]
    s0 = min(slots, key=lambda x: (x.min_row, x.min_col))
    span = s0.max_col - s0.min_col
    return [(2, 2 + span), (10, 10 + span), (17, 17 + span)]


def _ensure_photo_slots(ws, needed: int) -> list:
    """
    إن زادت الصور عن المربعات الموجودة:
    يُنشئ صفوفاً جديدة بنفس الطريقة بجانب/تحت الموجود (B/J/Q).
    """
    slots = _find_value_photo_slots(ws)
    if needed <= len(slots):
        return slots

    if not slots:
        # أنشئ أول صف قياسي إن لم يوجد شيء
        start_row = 60 if "HVAC" in (ws.title or "") or "CLEAN" in (ws.title or "").upper() else 110
        row_span = 7
        col_groups = [(2, 9), (10, 16), (17, 24)]
        last_row = start_row - 1
    else:
        row_span = slots[0].max_row - slots[0].min_row + 1
        col_groups = _photo_col_groups(slots)
        last_row = max(s.max_row for s in slots)
        # انسخ ارتفاع الصف من أول مربع
        template_heights = []
        for r in range(slots[0].min_row, slots[0].max_row + 1):
            template_heights.append(ws.row_dimensions[r].height)

    safety = 0
    while len(slots) < needed and safety < 80:
        safety += 1
        start = last_row + 1
        end = start + row_span - 1

        # ارتفاع الصفوف مثل القالب
        if slots:
            for i in range(row_span):
                h = template_heights[i] if i < len(template_heights) else template_heights[-1]
                if h:
                    ws.row_dimensions[start + i].height = h
        else:
            for i in range(row_span):
                ws.row_dimensions[start + i].height = 18

        # عمود Comment
        try:
            ws.merge_cells(start_row=start, start_column=1, end_row=end, end_column=1)
            ws.cell(start, 1).value = "Comment"
        except Exception:
            pass

        # ثلاثة مربعات جنب بعض: B / J / Q
        for c1, c2 in col_groups:
            try:
                ws.merge_cells(
                    start_row=start,
                    start_column=c1,
                    end_row=end,
                    end_column=c2,
                )
                ws.cell(start, c1).value = None
            except Exception:
                # إن كان مدموجاً مسبقاً تجاهل
                pass

        last_row = end
        slots = _find_value_photo_slots(ws)
        # إن فشل الاكتشاف لسبب ما، أضف نطاقاً يدوياً عبر إعادة البحث عن الدمج الجديد
        if len(slots) < needed:
            # تأكد أن الدمج الجديد يُرى
            fresh = [
                rng
                for rng in ws.merged_cells.ranges
                if rng.min_row == start and _is_photo_slot_merge(rng)
            ]
            if fresh and len(_find_value_photo_slots(ws)) <= len(slots):
                # أجبر إدراجها في القائمة عبر قيمة فارغة مقبولة
                for rng in fresh:
                    if ws.cell(rng.min_row, rng.min_col).value not in (None, ""):
                        continue
                slots = _find_value_photo_slots(ws)

    return _find_value_photo_slots(ws)


def _clear_photos_in_slot_area(ws, slots: list) -> None:
    """استبدال: احذف أي صور سابقة داخل منطقة مربعات الصور فقط."""
    if not slots:
        return
    min_r = min(s.min_row for s in slots) - 1
    max_r = max(s.max_row for s in slots) + 1
    # AnchorMarker.row صفرية الأساس
    min_a = max(0, min_r - 1)
    max_a = max_r  # inclusive-ish
    keep = []
    for img in list(ws._images):
        anchor = img.anchor
        row = None
        col = None
        if hasattr(anchor, "_from") and anchor._from is not None:
            row = int(anchor._from.row)
            col = int(anchor._from.col)
        # أبقِ شعارات الرأس والزوايا (أعمدة عالية مثل W/X للشعارات الجانبية فوق المنطقة)
        if row is None:
            keep.append(img)
            continue
        if row < min_a or row > max_a:
            keep.append(img)
            continue
        # صور داخل أعمدة مربعات B/J/Q تقريباً (0-based: 1, 9, 16)
        if col is not None and col >= 20:
            # شعار جانبي صغير — أبقه
            keep.append(img)
            continue
        # غير ذلك: صورة قديمة داخل المربعات → تُستبدل (لا تُبقى)
    ws._images = keep


def _place_image_in_merge(ws, rng, blob: bytes) -> None:
    """يضع الصورة داخل مربع #VALUE! بمقاس المربع (متوافق مع إكسل)."""
    from openpyxl.cell.cell import MergedCell
    from openpyxl.drawing.spreadsheet_drawing import (
        AnchorMarker,
        OneCellAnchor,
        TwoCellAnchor,
        XDRPositiveSize2D,
    )
    from openpyxl.utils.units import pixels_to_EMU

    # امسح نص #VALUE! / Mandatory دون فك الدمج
    try:
        anchor_cell = ws.cell(rng.min_row, rng.min_col)
        if not isinstance(anchor_cell, MergedCell):
            anchor_cell.value = None
    except Exception:
        pass

    px_w, px_h = _merge_size_px(ws, rng)
    buf = _prepare_image(blob, box=(px_w, px_h))
    xl_img = XLImage(buf)
    xl_img.width = px_w
    xl_img.height = px_h

    # TwoCellAnchor يربط بأركان المربع + OneCell احتياطي إن فشل
    margin = 6000
    _from = AnchorMarker(
        col=rng.min_col - 1,
        colOff=margin,
        row=rng.min_row - 1,
        rowOff=margin,
    )
    to = AnchorMarker(
        col=rng.max_col,  # نهاية المربع (مثل قوالب الإكسل)
        colOff=0,
        row=rng.max_row,
        rowOff=0,
    )
    try:
        xl_img.anchor = TwoCellAnchor(editAs="twoCell", _from=_from, to=to)
    except Exception:
        xl_img.anchor = OneCellAnchor(
            _from=_from,
            ext=XDRPositiveSize2D(cx=pixels_to_EMU(px_w), cy=pixels_to_EMU(px_h)),
        )
    ws.add_image(xl_img)


def _add_photos(ws, board_blobs: list[bytes], work_blobs: list[bytes], photo_label: str) -> None:
    """
    استبدال الصور داخل مربعات القالب (#VALUE! ثم المجاور الفارغ/إلزامي/اختياري).
    إن زادت الصور يُنشئ مربعات جديدة بنفس الطريقة جنبها/تحتها.
    """
    all_photos = list(board_blobs) + list(work_blobs)
    if not all_photos:
        return

    slots = _ensure_photo_slots(ws, len(all_photos))
    if not slots:
        return

    # استبدال: امسح الصور القديمة من المربعات ثم ضع الجديدة مكانها
    _clear_photos_in_slot_area(ws, slots)

    for idx, blob in enumerate(all_photos):
        if idx >= len(slots):
            break
        try:
            _place_image_in_merge(ws, slots[idx], blob)
        except Exception:
            continue


def save_daily_report(
    xlsx_path: Path,
    header: dict[str, Any],
    sheets_payload: list[dict[str, Any]],
    photos: dict[str, dict[str, list[tuple[bytes, str]]]] | None = None,
    output_path: Path | None = None,
) -> Path:
    """
    sheets_payload: [{key, items:[{id, done}]}]
    photos: {sheet_key: {"board":[(bytes,ext)], "work":[(bytes,ext)]}}
    """
    xlsx_path = Path(xlsx_path)
    output_path = Path(output_path) if output_path else xlsx_path
    wb = load_workbook(xlsx_path)

    done_map: dict[str, dict[str, bool]] = {}
    client_cells_map: dict[str, dict[str, str]] = {}
    for sh in sheets_payload:
        key = normalize_sheet_key(sh.get("key") or "")
        if not key:
            continue
        done_map[key] = {it["id"]: bool(it.get("done")) for it in (sh.get("items") or []) if it.get("id")}
        client_cells_map[key] = {
            it["id"]: it["done_cell"]
            for it in (sh.get("items") or [])
            if it.get("id") and it.get("done_cell")
        }

    # طبّع مفاتيح الصور
    norm_photos: dict[str, dict[str, list]] = {}
    if photos:
        for k, kinds in photos.items():
            nk = normalize_sheet_key(k)
            norm_photos[nk] = kinds

    for key, meta in SHEET_META.items():
        sheet_name = meta["sheet_name"]
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        try:
            _write_header(ws, header)
        except Exception:
            pass

        structure_items = extract_sheet_items(ws)
        wanted = done_map.get(key, {})
        client_cells = client_cells_map.get(key, {})

        for it in structure_items:
            if it["id"] not in wanted:
                continue
            cell = client_cells.get(it["id"]) or it["done_cell"]
            _set_done(ws, cell, wanted[it["id"]])

        if key in norm_photos:
            board = [b for b, _e in norm_photos[key].get("board", [])]
            work = [b for b, _e in norm_photos[key].get("work", [])]
            try:
                _add_photos(ws, board, work, meta["photo_label"])
            except Exception:
                pass

    tmp = output_path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    try:
        tmp.replace(output_path)
    except PermissionError:
        alt = output_path.with_name(output_path.stem + "_محدث" + output_path.suffix)
        tmp.replace(alt)
        return alt
    return output_path


def load_state(user) -> dict[str, Any]:
    path = user_daily_state_path(user)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(user, state: dict[str, Any]) -> None:
    path = user_daily_state_path(user)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
