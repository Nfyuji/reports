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


def _is_photo_slot_merge(rng) -> bool:
    """مربع صورة في القالب: أعمدة B أو J أو Q بعرض/ارتفاع مناسب."""
    if rng.min_col not in (2, 10, 17):  # B, J, Q
        return False
    if (rng.max_col - rng.min_col) < 4:
        return False
    if (rng.max_row - rng.min_row) < 3:
        return False
    return True


def _is_value_error(val) -> bool:
    return str(val or "").strip().upper() in {"#VALUE!", "#VALUE"}


def _is_optional_label(val) -> bool:
    s = str(val or "")
    return "OPTIONAL" in s.upper() or "إختياري" in s or "اختياري" in s


def _is_mandatory_label(val) -> bool:
    s = str(val or "")
    return "MANDATORY" in s.upper() or "إلزامي" in s


def _photo_section_start_row(ws) -> int:
    """أول صف لمنطقة مربعات الصور (#VALUE!)."""
    for rng in ws.merged_cells.ranges:
        if not _is_photo_slot_merge(rng):
            continue
        if _is_value_error(ws.cell(rng.min_row, rng.min_col).value):
            return rng.min_row
    # بعد حفظ سابق قد تُمسح #VALUE! — ابحث عنوان التقرير المصور
    for r in range(40, min(ws.max_row or 40, 200) + 1):
        a = ws.cell(r, 1).value
        if a and ("مواصفات" in str(a) or "Photo report" in str(a)):
            return r + 4
    title = (ws.title or "").upper()
    if "O&M" in title or title == "O&M":
        return 110
    return 60


def _find_value_photo_slots(ws, include_optional: bool = False) -> list:
    """
    مربعات الصور الصحيحة فقط:
    1) خلايا #VALUE!
    2) ثم الفارغ بنفس الشبكة
    3) ثم إلزامي
    4) اختياري فقط إذا include_optional=True
    الترتيب: صف ثم B→J→Q  (لا تذهب لصفحة أخيرة قبل امتلاء الشبكة)
    """
    start_row = _photo_section_start_row(ws)
    primary = []  # #VALUE!
    empty = []
    mandatory = []
    optional = []

    for rng in ws.merged_cells.ranges:
        if not _is_photo_slot_merge(rng):
            continue
        if rng.min_row < start_row:
            continue
        val = ws.cell(rng.min_row, rng.min_col).value
        if _is_value_error(val):
            primary.append(rng)
        elif _is_optional_label(val):
            optional.append(rng)
        elif _is_mandatory_label(val):
            mandatory.append(rng)
        elif val is None or str(val).strip() == "":
            empty.append(rng)

    def _sort(slots):
        return sorted(slots, key=lambda r: (r.min_row, r.min_col))

    out = _sort(primary) + _sort(empty) + _sort(mandatory)
    if include_optional:
        out += _sort(optional)
    return out


def _photo_col_groups(slots: list) -> list[tuple[int, int]]:
    if not slots:
        return [(2, 9), (10, 16), (17, 24)]
    by_row: dict[int, list] = {}
    for s in slots:
        by_row.setdefault(s.min_row, []).append(s)
    for _r, group in sorted(by_row.items()):
        if len(group) >= 3:
            group = sorted(group, key=lambda x: x.min_col)
            return [(g.min_col, g.max_col) for g in group[:3]]
    return [(2, 9), (10, 16), (17, 24)]


def _first_optional_row(ws) -> int | None:
    rows = []
    for rng in ws.merged_cells.ranges:
        if not _is_photo_slot_merge(rng):
            continue
        if _is_optional_label(ws.cell(rng.min_row, rng.min_col).value):
            rows.append(rng.min_row)
    return min(rows) if rows else None


def _ensure_photo_slots(ws, needed: int) -> list:
    """
    يملأ مربعات #VALUE!/الفارغ/إلزامي أولاً.
    إن احتجنا أكثر: يُنشئ صفوفاً جديدة قبل منطقة Optional (ليس في آخر الصفحة).
    """
    slots = _find_value_photo_slots(ws, include_optional=False)
    if needed <= len(slots):
        return slots[:needed]

    # استخدم الاختياري فقط بعد امتلاء الشبكة الأساسية
    slots = _find_value_photo_slots(ws, include_optional=True)
    if needed <= len(slots):
        return slots[:needed]

    row_span = 7
    col_groups = _photo_col_groups(slots) if slots else [(2, 9), (10, 16), (17, 24)]
    if slots:
        row_span = slots[0].max_row - slots[0].min_row + 1
        template_heights = [
            ws.row_dimensions[r].height for r in range(slots[0].min_row, slots[0].max_row + 1)
        ]
        last_row = max(s.max_row for s in slots)
    else:
        template_heights = [18] * row_span
        last_row = _photo_section_start_row(ws) - 1

    opt_row = _first_optional_row(ws)
    # إن وُجد Optional، أدرج الصفوف الجديدة قبله عبر البناء بعد آخر مربع غير اختياري
    non_opt = _find_value_photo_slots(ws, include_optional=False)
    if non_opt:
        last_row = max(s.max_row for s in non_opt)

    safety = 0
    while len(_find_value_photo_slots(ws, include_optional=True)) < needed and safety < 40:
        safety += 1
        start = last_row + 1
        # لا تقفز بعيدًا بعد Optional إن أمكن — أنشئ مباشرة تحت آخر مربع أساسي
        if opt_row is not None and start >= opt_row:
            start = last_row + 1
        end = start + row_span - 1
        for i in range(row_span):
            h = template_heights[i] if i < len(template_heights) else 18
            if h:
                ws.row_dimensions[start + i].height = h
        try:
            ws.merge_cells(start_row=start, start_column=1, end_row=end, end_column=1)
            ws.cell(start, 1).value = "Comment"
        except Exception:
            pass
        for c1, c2 in col_groups:
            try:
                ws.merge_cells(start_row=start, start_column=c1, end_row=end, end_column=c2)
                ws.cell(start, c1).value = None
            except Exception:
                pass
        last_row = end

    return _find_value_photo_slots(ws, include_optional=True)[: max(needed, 1)]


def _clear_photos_in_slot_area(ws, slots: list) -> None:
    """احذف أي صور عائمة/قديمة في منطقة التقرير المصور (استبدال نظيف)."""
    if not slots:
        return
    # امسح من قبل أول مربع بقليل حتى آخر مربع — لإزالة الصور الغلط فوق #VALUE!
    min_r = max(45, min(s.min_row for s in slots) - 15)
    max_r = max(s.max_row for s in slots) + 5
    min_a = max(0, min_r - 1)
    max_a = max_r
    keep = []
    for img in list(ws._images):
        anchor = img.anchor
        if not hasattr(anchor, "_from") or anchor._from is None:
            keep.append(img)
            continue
        row = int(anchor._from.row)
        col = int(anchor._from.col)
        if row < min_a or row > max_a:
            keep.append(img)
            continue
        if col >= 20:
            keep.append(img)
            continue
        # صورة داخل/فوق مربعات الصور → تُحذف للاستبدال
    ws._images = keep


def _place_image_in_merge(ws, rng, blob: bytes) -> None:
    """يضع الصورة داخل مربع #VALUE! نفسه (إرساء على الخلية B/J/Q)."""
    from openpyxl.cell.cell import MergedCell

    # امسح #VALUE! من زاوية المربع
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

    # الأوثق في إكسل: إرساء OneCell على زاوية المربع بمقاس المربع
    cell = f"{get_column_letter(rng.min_col)}{rng.min_row}"
    ws.add_image(xl_img, cell)


def _add_photos(ws, board_blobs: list[bytes], work_blobs: list[bytes], photo_label: str) -> None:
    """استبدال الصور داخل مربعات #VALUE! ثم المجاور — ليس فوقها ولا في آخر الصفحة."""
    all_photos = list(board_blobs) + list(work_blobs)
    if not all_photos:
        return

    slots = _ensure_photo_slots(ws, len(all_photos))
    if not slots:
        return

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
