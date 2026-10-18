# -*- coding: utf-8 -*-
"""تكامل WhatsApp عبر Green API — استقبال صور من رقم محدد وإرسال الملف الجاهز."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import auth_store

# انتظر دقيقة صمت بعد آخر صورة قبل سؤال التأكيد
PHOTO_QUIET_SECONDS = 60
_watchdog_started = False
_watchdog_lock = threading.Lock()


def _env_or_setting(env_key: str, setting_key: str, default: str = "") -> str:
    """يفضّل متغير البيئة (للاستضافة) ثم إعداد قاعدة البيانات."""
    val = (os.environ.get(env_key) or "").strip()
    if val:
        return val
    return auth_store.get_setting(setting_key, default)


def _cfg() -> dict[str, str]:
    return {
        "id_instance": _env_or_setting("GREEN_ID_INSTANCE", "green_id_instance"),
        "api_token": _env_or_setting("GREEN_API_TOKEN", "green_api_token"),
        "api_url": _env_or_setting(
            "GREEN_API_URL", "green_api_url", "https://api.green-api.com"
        ).rstrip("/"),
        "media_url": _env_or_setting(
            "GREEN_MEDIA_URL", "green_media_url", "https://media.green-api.com"
        ).rstrip("/"),
        "allowed_phone": _env_or_setting("GREEN_ALLOWED_PHONE", "green_allowed_phone"),
        "user_id": _env_or_setting("GREEN_USER_ID", "green_user_id"),
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
    """يحول أي شكل إلى أرقام دولية بدون + مثل 967714705660"""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    # يمني محلي: 07xxxxxxxx → 9677xxxxxxxx
    if digits.startswith("07") and len(digits) == 10:
        digits = "967" + digits[1:]
    elif digits.startswith("7") and len(digits) == 9:
        digits = "967" + digits
    # سعودي محلي: 05xxxxxxxx → 9665xxxxxxxx
    elif digits.startswith("05") and len(digits) == 10:
        digits = "966" + digits[1:]
    elif digits.startswith("5") and len(digits) == 9:
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


def _inbox_dir(phone: str) -> Path:
    auth_store.ensure_dirs()
    d = auth_store.DATA_DIR / "wa_inbox" / normalize_phone(phone)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(phone: str) -> Path:
    auth_store.ensure_dirs()
    return auth_store.DATA_DIR / "wa_sessions" / f"{normalize_phone(phone)}.json"


def session_get(phone: str) -> dict[str, Any]:
    path = _session_path(phone)
    if not path.exists():
        return {
            "stage": "idle",
            "chat_id": "",
            "last_photo_at": 0.0,
            "ack_sent": False,
            "confirm_sent": False,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "stage": "idle",
            "chat_id": "",
            "last_photo_at": 0.0,
            "ack_sent": False,
            "confirm_sent": False,
        }


def session_set(phone: str, **kwargs: Any) -> dict[str, Any]:
    sess = session_get(phone)
    sess.update(kwargs)
    path = _session_path(phone)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")
    return sess


def session_clear(phone: str) -> None:
    path = _session_path(phone)
    if path.exists():
        path.unlink(missing_ok=True)


def inbox_add(phone: str, blob: bytes, ext: str, name: str) -> int:
    d = _inbox_dir(phone)
    safe_ext = ext if ext.startswith(".") else f".{ext}"
    fname = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}{safe_ext}"
    meta = {"name": name or fname, "ext": safe_ext}
    (d / fname).write_bytes(blob)
    (d / f"{fname}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return inbox_count(phone)


def inbox_clear(phone: str) -> None:
    d = _inbox_dir(phone)
    if d.exists():
        for p in d.iterdir():
            try:
                p.unlink()
            except OSError:
                pass
    session_clear(phone)


def inbox_count(phone: str) -> int:
    d = _inbox_dir(phone)
    if not d.exists():
        return 0
    return len([p for p in d.iterdir() if p.is_file() and p.suffix.lower() != ".json"])


def inbox_photos(phone: str) -> list[tuple[bytes, str, str]]:
    d = _inbox_dir(phone)
    if not d.exists():
        return []
    out: list[tuple[bytes, str, str]] = []
    files = sorted(
        [p for p in d.iterdir() if p.is_file() and p.suffix.lower() != ".json"],
        key=lambda p: p.name,
    )
    for p in files:
        name = p.name
        ext = p.suffix or ".jpg"
        meta_path = d / f"{p.name}.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                name = meta.get("name") or name
                ext = meta.get("ext") or ext
            except Exception:
                pass
        out.append((p.read_bytes(), ext, name))
    return out


def start_watchdog() -> None:
    """مراقبة صمت الصور لمدة دقيقة ثم سؤال التأكيد مرة واحدة."""
    global _watchdog_started
    with _watchdog_lock:
        if _watchdog_started:
            return
        _watchdog_started = True
    t = threading.Thread(target=_watchdog_loop, name="wa-watchdog", daemon=True)
    t.start()


def _watchdog_loop() -> None:
    while True:
        time.sleep(5)
        try:
            _watchdog_tick()
        except Exception:
            continue


def _watchdog_tick() -> None:
    sess_dir = auth_store.DATA_DIR / "wa_sessions"
    if not sess_dir.exists():
        return
    now = time.time()
    for path in list(sess_dir.glob("*.json")):
        try:
            sess = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if sess.get("stage") != "collecting" or sess.get("confirm_sent"):
            continue
        last = float(sess.get("last_photo_at") or 0)
        if not last or (now - last) < PHOTO_QUIET_SECONDS:
            continue
        phone = path.stem
        n = inbox_count(phone)
        if n <= 0:
            continue
        # مطالبة ذرّية تقريباً: نعلّم confirm_sent قبل الإرسال
        sess["stage"] = "await_confirm"
        sess["confirm_sent"] = True
        path.write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")
        chat_id = sess.get("chat_id") or phone_to_chat_id(phone)
        try:
            send_text(chat_id, _confirm_prompt(n))
        except Exception:
            # أعد المحاولة لاحقاً
            sess["confirm_sent"] = False
            sess["stage"] = "collecting"
            path.write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")


HELP_TEXT = (
    "أوامر واتساب للتقرير:\n"
    "• أرسل كل الصور دفعة واحدة (أستقبل بهدوء دقيقة بعد آخر صورة)\n"
    "• بعد السؤال اكتب: ايوه → ثم أرسل الملاحظات\n"
    "• الملاحظات تُعبّئ الشريحة الأولى + نقاط الملاحظات عبر Gemini\n"
    "• اكتب: مسح → حذف الصور والبدء من جديد\n"
    "• اكتب: عدد / مساعدة"
)

# ردود الموافقة / الرفض
_YES = {
    "ايوه",
    "ايوا",
    "ايوة",
    "نعم",
    "اجل",
    "أجل",
    "تمام",
    "خلص",
    "خلاص",
    "جاهز",
    "ارسال",
    "ارسل",
    "تقرير",
    "ready",
    "send",
    "yes",
    "y",
    "ok",
    "اوك",
    "أوك",
}
_NO = {"لا", "لأ", "لاا", "no", "n", "كمل", "زياده", "زيادة"}


def _norm_cmd(text: str) -> str:
    t = (text or "").strip()
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
    return t.lower()


def _confirm_prompt(n: int) -> str:
    return (
        f"وصلتني {n} صورة ✅\n"
        f"هل هذه كلها؟\n"
        f"• اكتب: ايوه → بعدها أطلب منك الملاحظات ثم أرسل العرض\n"
        f"• أو كمّل إرسال صور (بانتظار دقيقة بعد آخر صورة)\n"
        f"• اكتب: مسح → أبدأ من جديد"
    )


def _notes_prompt() -> str:
    return (
        "تمام ✅\n"
        "أرسل الآن الملاحظات / نص التقرير كاملاً:\n"
        "(المدرسة، رقم الوزارة، المهندس، والملاحظات…)\n"
        "راح أعبّي الشريحة الأولى والملاحظات عبر Gemini ثم أرسل لك العرض جاهز."
    )


def configure_webhook(webhook_url: str) -> dict[str, Any]:
    """يضبط Webhook تلقائياً في Green API."""
    if not is_configured():
        return {"ok": False, "error": "غير مضبوط"}
    url = (webhook_url or "").strip()
    if not url:
        return {"ok": False, "error": "لا يوجد رابط"}
    return _http_json(
        _api_url("setSettings"),
        {
            "webhookUrl": url,
            "incomingWebhook": "yes",
            "outgoingWebhook": "no",
            "stateWebhook": "no",
            "outgoingAPIMessageWebhook": "no",
        },
    )


def handle_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """يعالج إشعار Green API — يرد فقط على الرقم المسموح، ويصمت لغيره."""
    start_watchdog()
    if not is_configured():
        return {"ok": False, "error": "Green API غير مضبوط"}

    typ = payload.get("typeWebhook") or ""
    if typ != "incomingMessageReceived":
        return {"ok": True, "ignored": typ or "unknown"}

    sender = (payload.get("senderData") or {})
    chat_id = sender.get("chatId") or sender.get("sender") or ""
    # صمت تام لأي رقم غير المسموح — لا رد ولا معالجة
    if not chat_id or not is_allowed_sender(chat_id):
        return {"ok": True, "ignored": "unauthorized_sender", "chatId": chat_id}

    phone = chat_id_to_phone(chat_id)
    msg = payload.get("messageData") or {}
    mtype = msg.get("typeMessage") or ""
    sess = session_get(phone)

    # صور (أو مستند صورة) — تجميع صامت ثم سؤال بعد دقيقة
    if mtype in {"imageMessage", "documentMessage"}:
        fdata = msg.get("fileMessageData") or {}
        mime = (fdata.get("mimeType") or "").lower()
        name = fdata.get("fileName") or "photo.jpg"
        if mtype == "documentMessage" and not (
            mime.startswith("image/") or name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ):
            send_text(chat_id, "أرسل صور فقط من فضلك.")
            return {"ok": True, "ignored": "non_image_document"}

        url = fdata.get("downloadUrl") or ""
        if not url:
            send_text(chat_id, "تعذر تحميل الصورة (لا يوجد رابط).")
            return {"ok": False, "error": "no_download_url"}
        try:
            blob = download_url_bytes(url)
        except Exception as e:
            send_text(chat_id, f"فشل تحميل الصورة: {e}")
            return {"ok": False, "error": str(e)}

        ext = ".png" if ("png" in mime or name.lower().endswith(".png")) else ".jpg"
        n = inbox_add(phone, blob, ext, name)
        first_ack = not sess.get("ack_sent")
        session_set(
            phone,
            stage="collecting",
            chat_id=chat_id,
            last_photo_at=time.time(),
            ack_sent=True,
            confirm_sent=False,
        )
        # رسالة واحدة فقط عند أول صورة في الدفعة — بدون سؤال بعد كل صورة
        if first_ack:
            send_text(
                chat_id,
                "تم بدء استلام الصور ✅\n"
                "أرسل كل الصور براحتك.\n"
                f"بعد مرور دقيقة من آخر صورة راح أسألك: هل هذه كلها؟\n"
                f"(الآن: {n})",
            )
        return {"ok": True, "action": "photo", "count": n, "quiet": True}

    # نص
    text = ""
    if mtype == "textMessage":
        text = ((msg.get("textMessageData") or {}).get("textMessage") or "").strip()
    elif mtype == "extendedTextMessage":
        text = ((msg.get("extendedTextMessageData") or {}).get("text") or "").strip()

    if not text:
        return {"ok": True, "ignored": "empty_text"}

    low = _norm_cmd(text)
    stage = sess.get("stage") or "idle"

    if low in {"مساعده", "help", "?", "؟"}:
        send_text(chat_id, HELP_TEXT)
        return {"ok": True, "action": "help"}

    if low in {"مسح", "حذف", "clear"}:
        inbox_clear(phone)
        send_text(chat_id, "تم المسح. أرسل الصور من جديد متى ما حاب.")
        return {"ok": True, "action": "clear"}

    if low in {"عدد", "count"}:
        send_text(chat_id, f"الصور المستلمة الآن: {inbox_count(phone)}")
        return {"ok": True, "action": "count"}

    if low in _NO:
        session_set(
            phone,
            stage="collecting",
            chat_id=chat_id,
            confirm_sent=False,
            last_photo_at=time.time(),
            ack_sent=True,
        )
        send_text(
            chat_id,
            f"تمام، كمّل إرسال الصور.\nعندي حالياً: {inbox_count(phone)}\n"
            "بعد دقيقة من توقفك راح أسأل مرة ثانية.",
        )
        return {"ok": True, "action": "continue"}

    # موافقة → اطلب الملاحظات (لا ترسل الملف بعد)
    if low in _YES or low.replace(" ", "") in _YES:
        if inbox_count(phone) <= 0:
            send_text(chat_id, "ما عندي صور بعد. أرسل الصور أولاً.")
            return {"ok": False, "error": "no_photos"}
        session_set(phone, stage="await_notes", chat_id=chat_id, confirm_sent=True)
        send_text(chat_id, _notes_prompt())
        return {"ok": True, "action": "ask_notes"}

    # مرحلة الملاحظات: أي نص طويل يُفسَّر عبر Gemini ثم يُرسل العرض
    if stage == "await_notes":
        return _parse_notes_and_send(chat_id, phone, text)

    n = inbox_count(phone)
    if stage in {"collecting", "await_confirm"} and n:
        send_text(
            chat_id,
            f"عندي {n} صورة.\n"
            "انتظر سؤال التأكيد بعد دقيقة من آخر صورة، أو اكتب: ايوه",
        )
    else:
        send_text(chat_id, "أرسل الصور أولاً. للمساعدة اكتب: مساعدة")
    return {"ok": True, "action": "unknown_cmd"}


def _parse_notes_and_send(chat_id: str, phone: str, raw_text: str) -> dict[str, Any]:
    send_text(chat_id, "جاري تحليل الملاحظات عبر Gemini وتعبئة الشريحة الأولى…")
    try:
        import ai_parse

        parsed = ai_parse.parse_report_text(raw_text, prefer_gemini=True)
    except Exception as e:
        send_text(chat_id, f"فشل تحليل النص: {e}\nأعد إرسال الملاحظات.")
        return {"ok": False, "error": str(e)}

    return _build_and_send_report(
        chat_id,
        phone,
        cover_override=parsed.get("cover") or {},
        observations=parsed.get("observations") or [],
    )


def _build_and_send_report(
    chat_id: str,
    phone: str,
    cover_override: dict[str, str] | None = None,
    observations: list[str] | None = None,
) -> dict[str, Any]:
    photos = inbox_photos(phone)
    if not photos:
        send_text(chat_id, "ما عندي صور بعد. أرسل الصور أولاً ثم الملاحظات.")
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
        if cover_override:
            for k, v in cover_override.items():
                if str(v or "").strip():
                    cover[k] = str(v).strip()
        cover["date"] = (cover.get("date") or "").strip() or today_date_str()
        if user.display_name and not (cover.get("engineer") or "").strip():
            cover["engineer"] = user.display_name

        obs = observations if observations is not None else (data.get("observations") or [])
        wa_blobs = [(b, e) for b, e, _n in photos]

        # صور واتساب + بيانات الغلاف/الملاحظات من Gemini
        save_report(
            path,
            cover,
            obs,
            wa_blobs,
            output_path=path,
        )

        file_bytes = Path(path).read_bytes()
        school = (cover.get("school") or "مدرسة").strip() or "مدرسة"
        eng = (cover.get("engineer") or user.display_name or "مهندس").strip()
        date = (cover.get("date") or today_date_str()).replace("/", "-")
        fname = f"{school}_{eng}_{date}.pptx".replace(" ", "_")

        send_text(
            chat_id,
            f"جاري إرسال العرض…\n{len(wa_blobs)} صورة · {len(obs)} ملاحظة",
        )
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
