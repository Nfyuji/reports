# -*- coding: utf-8 -*-
"""تكامل WhatsApp عبر Green API — استقبال صور من رقم محدد وإرسال الملف الجاهز."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import auth_store

# صور واردة مؤقتاً حسب رقم المرسل
# phone -> list[(bytes, ext, name)]
INBOX: dict[str, list[tuple[bytes, str, str]]] = {}


def _cfg() -> dict[str, str]:
    return {
        "id_instance": auth_store.get_setting("green_id_instance"),
        "api_token": auth_store.get_setting("green_api_token"),
        "api_url": auth_store.get_setting("green_api_url", "https://api.green-api.com").rstrip("/"),
        "media_url": auth_store.get_setting("green_media_url", "https://media.green-api.com").rstrip("/"),
        "allowed_phone": auth_store.get_setting("green_allowed_phone"),
        "user_id": auth_store.get_setting("green_user_id"),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["id_instance"] and c["api_token"] and c["allowed_phone"])


def save_config(
    id_instance: str,
    api_token: str,
    allowed_phone: str,
    user_id: str = "",
    api_url: str = "",
    media_url: str = "",
    keep_token: bool = False,
) -> None:
    auth_store.set_setting("green_id_instance", id_instance)
    # إن تُرك التوكن فارغاً مع keep_token نُبقي المحفوظ سابقاً
    if api_token or not keep_token:
        auth_store.set_setting("green_api_token", api_token)
    auth_store.set_setting("green_allowed_phone", normalize_phone(allowed_phone))
    auth_store.set_setting("green_user_id", str(user_id or "").strip())
    if api_url:
        auth_store.set_setting("green_api_url", api_url.rstrip("/"))
    if media_url:
        auth_store.set_setting("green_media_url", media_url.rstrip("/"))


def get_public_config() -> dict[str, Any]:
    c = _cfg()
    tok = c["api_token"]
    masked = (tok[:4] + "…" + tok[-4:]) if len(tok) > 8 else ("مضبوط" if tok else "")
    return {
        "configured": is_configured(),
        "id_instance": c["id_instance"],
        "api_token_masked": masked,
        "api_url": c["api_url"],
        "media_url": c["media_url"],
        "allowed_phone": c["allowed_phone"],
        "user_id": c["user_id"],
    }


def normalize_phone(phone: str) -> str:
    """يحول أي شكل إلى أرقام دولية بدون + مثل 9665xxxxxxxx"""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    # محلي سعودي 05xxxxxxxx
    if digits.startswith("05") and len(digits) == 10:
        digits = "966" + digits[1:]
    if digits.startswith("5") and len(digits) == 9:
        digits = "966" + digits
    return digits


def phone_to_chat_id(phone: str) -> str:
    p = normalize_phone(phone)
    if not p:
        return ""
    if "@" in (phone or ""):
        return phone.strip()
    return f"{p}@c.us"


def chat_id_to_phone(chat_id: str) -> str:
    return normalize_phone((chat_id or "").split("@")[0])


def is_allowed_sender(chat_id: str) -> bool:
    allowed = normalize_phone(_cfg()["allowed_phone"])
    if not allowed:
        return False
    return chat_id_to_phone(chat_id) == allowed


def _api_url(method: str) -> str:
    c = _cfg()
    return f"{c['api_url']}/waInstance{c['id_instance']}/{method}/{c['api_token']}"


def _media_url(method: str) -> str:
    c = _cfg()
    return f"{c['media_url']}/waInstance{c['id_instance']}/{method}/{c['api_token']}"


def _http_json(url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Green API HTTP {e.code}: {detail}") from e


def send_text(chat_id: str, message: str) -> dict:
    return _http_json(
        _api_url("sendMessage"),
        {"chatId": chat_id, "message": message},
    )


def send_file_bytes(chat_id: str, file_bytes: bytes, file_name: str, caption: str = "") -> dict:
    """يرسل ملفاً عبر sendFileByUpload (multipart)."""
    import uuid

    boundary = f"----moth{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )

    add_field("chatId", chat_id)
    if caption:
        add_field("caption", caption)
    add_field("fileName", file_name)

    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    req = urllib.request.Request(
        _media_url("sendFileByUpload"),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Green API upload HTTP {e.code}: {detail}") from e


def download_url_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def inbox_add(phone: str, blob: bytes, ext: str, name: str) -> int:
    key = normalize_phone(phone)
    INBOX.setdefault(key, []).append((blob, ext, name))
    return len(INBOX[key])


def inbox_clear(phone: str) -> None:
    INBOX.pop(normalize_phone(phone), None)


def inbox_count(phone: str) -> int:
    return len(INBOX.get(normalize_phone(phone), []))


def inbox_photos(phone: str) -> list[tuple[bytes, str, str]]:
    return list(INBOX.get(normalize_phone(phone), []))


HELP_TEXT = (
    "أوامر واتساب للتقرير:\n"
    "• أرسل الصور هنا مباشرة\n"
    "• اكتب: جاهز  أو  ارسال  → يجهّز الملف ويرسله لك\n"
    "• اكتب: مسح → يحذف الصور المنتظرة\n"
    "• اكتب: عدد → كم صورة وصلت\n"
    "• اكتب: مساعدة → هذا الشرح"
)


def handle_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """يعالج إشعار Green API ويعيد ملخصاً لما تم."""
    if not is_configured():
        return {"ok": False, "error": "Green API غير مضبوط"}

    typ = payload.get("typeWebhook") or ""
    if typ != "incomingMessageReceived":
        return {"ok": True, "ignored": typ or "unknown"}

    sender = (payload.get("senderData") or {})
    chat_id = sender.get("chatId") or sender.get("sender") or ""
    if not chat_id or not is_allowed_sender(chat_id):
        return {"ok": True, "ignored": "unauthorized_sender", "chatId": chat_id}

    phone = chat_id_to_phone(chat_id)
    msg = payload.get("messageData") or {}
    mtype = msg.get("typeMessage") or ""

    # صور
    if mtype == "imageMessage":
        fdata = msg.get("fileMessageData") or {}
        url = fdata.get("downloadUrl") or ""
        if not url:
            send_text(chat_id, "تعذر تحميل الصورة (لا يوجد رابط).")
            return {"ok": False, "error": "no_download_url"}
        try:
            blob = download_url_bytes(url)
        except Exception as e:
            send_text(chat_id, f"فشل تحميل الصورة: {e}")
            return {"ok": False, "error": str(e)}
        name = fdata.get("fileName") or "photo.jpg"
        n = inbox_add(phone, blob, ".jpg", name)
        send_text(chat_id, f"تم استلام الصورة ✅\nالمجموع الآن: {n}\nعند الانتهاء اكتب: جاهز")
        return {"ok": True, "action": "photo", "count": n}

    # نص
    text = ""
    if mtype == "textMessage":
        text = ((msg.get("textMessageData") or {}).get("textMessage") or "").strip()
    elif mtype == "extendedTextMessage":
        text = ((msg.get("extendedTextMessageData") or {}).get("text") or "").strip()

    if not text:
        return {"ok": True, "ignored": "empty_text"}

    low = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").strip().lower()

    if low in {"مساعدة", "help", "?", "؟"}:
        send_text(chat_id, HELP_TEXT)
        return {"ok": True, "action": "help"}

    if low in {"مسح", "حذف", "clear"}:
        inbox_clear(phone)
        send_text(chat_id, "تم مسح الصور المنتظرة.")
        return {"ok": True, "action": "clear"}

    if low in {"عدد", "count"}:
        send_text(chat_id, f"الصور المنتظرة: {inbox_count(phone)}")
        return {"ok": True, "action": "count"}

    if low in {"جاهز", "ارسال", "إرسال", "ارسل", "أرسل", "تقرير", "ready", "send"}:
        return _build_and_send_report(chat_id, phone)

    send_text(
        chat_id,
        "لم أفهم الأمر.\nأرسل صوراً أو اكتب: جاهز / مسح / مساعدة",
    )
    return {"ok": True, "action": "unknown_cmd"}


def _build_and_send_report(chat_id: str, phone: str) -> dict[str, Any]:
    photos = inbox_photos(phone)
    if not photos:
        send_text(chat_id, "لا توجد صور بعد. أرسل صوراً ثم اكتب: جاهز")
        return {"ok": False, "error": "no_photos"}

    uid_raw = _cfg()["user_id"]
    if not uid_raw:
        send_text(chat_id, "لم يُربط رقم واتساب بمستخدم في لوحة الإدارة.")
        return {"ok": False, "error": "no_user_link"}

    try:
        user = auth_store.get_user_by_id(int(uid_raw))
    except Exception:
        user = None
    if not user:
        send_text(chat_id, "المستخدم المرتبط غير موجود.")
        return {"ok": False, "error": "user_missing"}

    try:
        from report_engine import load_report, save_report, today_date_str

        path = auth_store.user_report_path(user)
        data = load_report(path)
        cover = dict(data.get("cover") or {})
        cover["date"] = today_date_str()
        if user.display_name and not (cover.get("engineer") or "").strip():
            cover["engineer"] = user.display_name

        # دمج صور الملف الحالية + صور واتساب
        existing = [
            (ph["blob"], ".jpg" if "png" not in (ph.get("content_type") or "") else ".png")
            for ph in (data.get("photos") or [])
        ]
        wa_blobs = [(b, e) for b, e, _n in photos]
        all_photos = existing + wa_blobs

        save_report(
            path,
            cover,
            data.get("observations") or [],
            all_photos,
            output_path=path,
        )

        file_bytes = Path(path).read_bytes()
        school = (cover.get("school") or "مدرسة").strip() or "مدرسة"
        eng = (cover.get("engineer") or user.display_name or "مهندس").strip()
        date = (cover.get("date") or today_date_str()).replace("/", "-")
        fname = f"{school}_{eng}_{date}.pptx".replace(" ", "_")

        send_text(chat_id, f"جاري إرسال التقرير… ({len(wa_blobs)} صورة من واتساب)")
        send_file_bytes(
            chat_id,
            file_bytes,
            fname,
            caption=f"التقرير جاهز ✅\n{school}\n{date}",
        )
        inbox_clear(phone)
        return {"ok": True, "action": "sent", "photos": len(wa_blobs), "file": fname}
    except Exception as e:
        send_text(chat_id, f"حدث خطأ أثناء تجهيز الملف:\n{e}")
        return {"ok": False, "error": str(e)}
