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

# ترتيب الواجهة حسب طلب المستخدم: أخضر صيانة → أحمر تكييف → أزرق نظافة
SHEET_META = {
    "O&M": {
        "key": "O&M",
        "ar": "صيانة",
        "en": "O&M",
        "color": "green",
        "photo_label": "صور الصيانة",
        "order": 1,
    },
    "HVAC": {
        "key": "HVAC",
        "ar": "تكييف",
        "en": "HVAC",
        "color": "red",
        "photo_label": "صور التكييف",
        "order": 2,
    },
    "CLEANING": {
        "key": "CLEANING",
        "ar": "نظافة",
        "en": "CLEANING",
        "color": "blue",
        "photo_label": "صور نظافة المبنى",
        "order": 3,
    },
}

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
    for key in ("O&M", "HVAC", "CLEANING"):
        if key not in wb.sheetnames:
            continue
        ws = wb[key]
        meta = SHEET_META[key]
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


def _prepare_image(blob: bytes, max_side: int = 900) -> io.BytesIO:
    im = PILImage.open(io.BytesIO(blob))
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")
    im.thumbnail((max_side, max_side), PILImage.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf


def _slot_sort_key(rng) -> tuple[int, int]:
    return (rng.min_row, rng.min_col)


def _find_value_photo_slots(ws) -> list:
    """
    مربعات الصور في التقرير المصور — الخلايا/الدمج التي فيها #VALUE!
    ومعها المربعات الفارغة المجاورة بنفس شكل الأعمدة (B/J/Q).
    """
    value_slots = []
    for rng in ws.merged_cells.ranges:
        anchor = ws.cell(rng.min_row, rng.min_col).value
        if anchor is None:
            continue
        if str(anchor).strip().upper() in {"#VALUE!", "#VALUE"}:
            value_slots.append(rng)

    if not value_slots:
        # بحث بدون دمج
        for row in ws.iter_rows(min_row=40, max_row=min(ws.max_row or 40, 220), max_col=24):
            for c in row:
                if c.value is not None and str(c.value).strip().upper() in {"#VALUE!", "#VALUE"}:
                    # لفّه كمدى وهمي 1 خلية عبر merged lookup لاحقاً
                    value_slots.append(type("R", (), {
                        "min_row": c.row, "max_row": c.row + 6,
                        "min_col": c.column, "max_col": min(c.column + 7, 24),
                    })())

    if not value_slots:
        return []

    min_row = min(r.min_row for r in value_slots) - 2
    max_row = max(r.max_row for r in value_slots) + 16

    # أضف مربعات فارغة في منطقة الصور بنفس نمط الأعمدة
    extras = []
    for rng in ws.merged_cells.ranges:
        if rng.min_row < min_row or rng.min_row > max_row:
            continue
        if rng.min_col not in (2, 10, 17):  # B, J, Q
            continue
        # عرض معقول لمربع صورة
        if (rng.max_col - rng.min_col) < 4 or (rng.max_row - rng.min_row) < 3:
            continue
        val = ws.cell(rng.min_row, rng.min_col).value
        if val is None or str(val).strip() == "" or str(val).strip().upper() in {"#VALUE!", "#VALUE"}:
            extras.append(rng)

    # دمج فريد حسب الزاوية
    seen = set()
    slots = []
    for rng in sorted(list(value_slots) + extras, key=_slot_sort_key):
        key = (rng.min_row, rng.min_col)
        if key in seen:
            continue
        seen.add(key)
        slots.append(rng)
    return slots


def _clear_photos_in_rows(ws, min_row: int, max_row: int) -> None:
    """يحذف الصور داخل صفوف مربعات #VALUE! فقط (لا يمس شعارات الرأس)."""
    keep = []
    for img in list(ws._images):
        anchor = img.anchor
        row = None
        if hasattr(anchor, "_from") and anchor._from is not None:
            row = int(anchor._from.row)
        if row is None or row < min_row or row > max_row:
            keep.append(img)
    ws._images = keep


def _estimate_slot_size_px(ws, rng) -> tuple[int, int]:
    """تقدير عرض/ارتفاع المربع بالبكسل من أعمدة/صفوف الدمج."""
    width = 0.0
    for c in range(rng.min_col, rng.max_col + 1):
        letter = get_column_letter(c)
        w = ws.column_dimensions[letter].width
        width += float(w or 8.5)
    height = 0.0
    for r in range(rng.min_row, rng.max_row + 1):
        h = ws.row_dimensions[r].height
        height += float(h or 15)
    # تقريب: عرض العمود~7px لكل وحدة، ارتفاع الصف~1.33px لكل نقطة
    px_w = max(120, int(width * 7.2))
    px_h = max(90, int(height * 1.35))
    return min(px_w, 420), min(px_h, 320)


def _add_photos(ws, board_blobs: list[bytes], work_blobs: list[bytes], photo_label: str) -> None:
    """يضع الصور داخل مربعات #VALUE! في قسم التقرير المصور."""
    slots = _find_value_photo_slots(ws)
    if not slots:
        return

    min_r = min(s.min_row for s in slots)
    max_r = max(s.max_row for s in slots)
    _clear_photos_in_rows(ws, min_r - 1, max_r + 1)

    # اللوحة أولاً ثم صور الأعمال
    all_photos = list(board_blobs) + list(work_blobs)
    if not all_photos:
        return

    from openpyxl.cell.cell import MergedCell

    for idx, blob in enumerate(all_photos):
        if idx >= len(slots):
            break
        rng = slots[idx]
        # امسح #VALUE! من زاوية المربع دون فك الدمج
        try:
            anchor_cell = ws.cell(rng.min_row, rng.min_col)
            if not isinstance(anchor_cell, MergedCell):
                anchor_cell.value = None
        except Exception:
            pass
        try:
            buf = _prepare_image(blob, max_side=1200)
            xl_img = XLImage(buf)
            w, h = _estimate_slot_size_px(ws, rng)
            # هامش صغير داخل المربع
            xl_img.width = max(100, w - 12)
            xl_img.height = max(80, h - 12)
            anchor = f"{get_column_letter(rng.min_col)}{rng.min_row}"
            ws.add_image(xl_img, anchor)
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
    for sh in sheets_payload:
        key = sh.get("key")
        if not key:
            continue
        done_map[key] = {it["id"]: bool(it.get("done")) for it in (sh.get("items") or []) if it.get("id")}

    for key in ("O&M", "HVAC", "CLEANING"):
        if key not in wb.sheetnames:
            continue
        ws = wb[key]
        try:
            _write_header(ws, header)
        except Exception:
            pass

        structure_items = extract_sheet_items(ws)
        wanted = done_map.get(key, {})
        # أيضاً خريطة done_cell من الطلب إن وُجدت
        client_cells = {}
        for sh in sheets_payload:
            if sh.get("key") == key:
                for it in sh.get("items") or []:
                    if it.get("id") and it.get("done_cell"):
                        client_cells[it["id"]] = it["done_cell"]

        for it in structure_items:
            if it["id"] not in wanted:
                continue
            cell = client_cells.get(it["id"]) or it["done_cell"]
            _set_done(ws, cell, wanted[it["id"]])

        if photos and key in photos:
            board = [b for b, _e in photos[key].get("board", [])]
            work = [b for b, _e in photos[key].get("work", [])]
            try:
                _add_photos(ws, board, work, SHEET_META[key]["photo_label"])
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
