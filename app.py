# -*- coding: utf-8 -*-
"""واجهة ويب متعددة المستخدمين — اشتراك شهري + نسخة تقرير منفصلة لكل مستخدم."""

from __future__ import annotations

import os
import secrets
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

import auth_store
from report_engine import load_report, photos_to_data_uris, save_report, _guess_ext

BASE = Path(__file__).resolve().parent

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# تهيئة قاعدة البيانات عند تشغيل gunicorn أيضاً
auth_store.init_db()

# صور كل مستخدم منفصلة: user_id -> {photo_id: (bytes, ext, name)}
PHOTO_STORES: dict[int, dict[str, tuple[bytes, str, str]]] = {}


def _photo_store() -> dict[str, tuple[bytes, str, str]]:
    uid = session.get("user_id")
    if not uid:
        return {}
    return PHOTO_STORES.setdefault(int(uid), {})


def _current_user() -> auth_store.User | None:
    uid = session.get("user_id")
    if not uid:
        return None
    user = auth_store.get_user_by_id(int(uid))
    if not user or not user.active or user.expired:
        session.clear()
        return None
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "يلزم تسجيل الدخول", "auth": False}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "غير مصرح"}), 403
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)

    return wrapper


def _reset_store_from_report(photos: list[dict]) -> list[dict]:
    store = _photo_store()
    store.clear()
    stored_meta = []
    for i, ph in enumerate(photos):
        pid = f"p{i}_{uuid.uuid4().hex[:8]}"
        ctype = ph.get("content_type") or "image/jpeg"
        ext = _guess_ext(None, ctype)
        name = ph.get("name") or f"صورة {i + 1}"
        store[pid] = (ph["blob"], ext, name)
        stored_meta.append({"id": pid, "blob": ph["blob"], "content_type": ctype, "name": name})
    return photos_to_data_uris(stored_meta)


# ---------- صفحات ----------


@app.route("/")
def home():
    if _current_user():
        return redirect(url_for("editor"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        code = (request.form.get("access_code") or "").strip()
        user, err = auth_store.authenticate(code)
        if err:
            error = err
        else:
            session.clear()
            session["user_id"] = user.id
            session["display_name"] = user.display_name
            return redirect(url_for("editor"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    uid = session.get("user_id")
    if uid and int(uid) in PHOTO_STORES:
        PHOTO_STORES.pop(int(uid), None)
    session.clear()
    return redirect(url_for("login"))


@app.route("/editor")
@login_required
def editor():
    user = _current_user()
    return render_template(
        "index.html",
        user_name=user.display_name,
        access_code=user.access_code,
        expires_at=user.expires_at,
        days_left=user.days_left,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password") or ""
        if password == auth_store.get_admin_password():
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))
        error = "كلمة المرور غير صحيحة"
    return render_template("admin_login.html", error=error)


@app.route("/admin")
@admin_required
def admin_panel():
    import ai_parse

    users = auth_store.list_users()
    master = auth_store.master_template_path()
    must_change = auth_store.is_default_admin_password()
    gkey = ai_parse.get_gemini_api_key()
    return render_template(
        "admin.html",
        users=users,
        master_name=master.name if master else None,
        must_change_password=must_change,
        gemini_configured=bool(gkey),
        gemini_masked=(gkey[:4] + "…" + gkey[-4:]) if len(gkey) > 8 else "",
    )


@app.route("/api/admin/change-password", methods=["POST"])
@admin_required
def api_admin_change_password():
    payload = request.get_json(force=True, silent=True) or {}
    current = payload.get("current") or ""
    new_password = payload.get("new_password") or ""
    confirm = payload.get("confirm") or ""
    if new_password != confirm:
        return jsonify({"ok": False, "error": "تأكيد كلمة المرور غير مطابق"}), 400
    try:
        auth_store.change_admin_password(current, new_password)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/admin/upload-template", methods=["POST"])
@admin_required
def api_admin_upload_template():
    """رفع قالب PowerPoint الرئيسي (مهم على Render لأن القالب غير موجود في Git)."""
    f = request.files.get("template")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "اختر ملف pptx"}), 400
    if not f.filename.lower().endswith(".pptx"):
        return jsonify({"ok": False, "error": "الملف يجب أن يكون .pptx"}), 400

    auth_store.ensure_dirs()
    dest = auth_store.MASTER_DIR / "قالب_التقرير_الفني.pptx"
    f.save(dest)
    return jsonify({"ok": True, "filename": dest.name, "size": dest.stat().st_size})


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


# ---------- API مستخدم ----------


@app.route("/api/me")
@login_required
def api_me():
    user = _current_user()
    return jsonify(
        {
            "ok": True,
            "name": user.display_name,
            "access_code": user.access_code,
            "expires_at": user.expires_at,
            "days_left": user.days_left,
        }
    )


@app.route("/api/report", methods=["GET"])
@login_required
def api_get_report():
    user = _current_user()
    try:
        path = auth_store.user_report_path(user)
        data = load_report(path)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    previews = _reset_store_from_report(data["photos"])
    return jsonify(
        {
            "ok": True,
            "filename": data["filename"],
            "path": data["path"],
            "cover": data["cover"],
            "observations": data["observations"],
            "photos": previews,
            "photo_count": data["photo_count"],
            "slide_count": data["slide_count"],
            "user": user.display_name,
            "expires_at": user.expires_at,
            "days_left": user.days_left,
        }
    )


@app.route("/api/photos/upload", methods=["POST"])
@login_required
def api_upload_photos():
    files = request.files.getlist("photos")
    if not files:
        return jsonify({"ok": False, "error": "لا توجد ملفات"}), 400

    store = _photo_store()
    added = []
    raw_for_preview = []
    for f in files:
        if not f or not f.filename:
            continue
        blob = f.read()
        if not blob:
            continue
        ext = _guess_ext(f.filename, f.mimetype)
        pid = f"u{uuid.uuid4().hex}"
        store[pid] = (blob, ext, f.filename)
        raw_for_preview.append(
            {"id": pid, "blob": blob, "content_type": f.mimetype or "image/jpeg", "name": f.filename}
        )

    previews = photos_to_data_uris(raw_for_preview)
    for i, prev in enumerate(previews):
        prev["id"] = raw_for_preview[i]["id"]
        added.append(prev)

    return jsonify({"ok": True, "photos": added})


@app.route("/api/save", methods=["POST"])
@login_required
def api_save():
    user = _current_user()
    payload = request.get_json(force=True, silent=True) or {}
    cover = payload.get("cover") or {}
    observations = payload.get("observations") or []
    photo_ids = payload.get("photo_ids") or []

    if not isinstance(observations, list):
        return jsonify({"ok": False, "error": "الملاحظات غير صالحة"}), 400

    store = _photo_store()
    photo_blobs: list[tuple[bytes, str]] = []
    missing = []
    for pid in photo_ids:
        item = store.get(pid)
        if not item:
            missing.append(pid)
            continue
        blob, ext, _name = item
        photo_blobs.append((blob, ext))

    if missing:
        return jsonify(
            {"ok": False, "error": f"صور مفقودة من الذاكرة ({len(missing)}). حدّث الصفحة وأعد المحاولة."}
        ), 400

    try:
        path = auth_store.user_report_path(user)
        saved = save_report(path, cover, observations, photo_blobs, output_path=path)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify(
        {
            "ok": True,
            "path": str(saved),
            "filename": Path(saved).name,
            "photo_count": len(photo_blobs),
        }
    )


@app.route("/api/download", methods=["GET"])
@login_required
def api_download():
    user = _current_user()
    path = auth_store.user_report_path(user)
    name = f"تقرير_{user.display_name}.pptx"
    return send_file(path, as_attachment=True, download_name=name)


# ---------- API إدارة ----------


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_users():
    users = [
        {
            "id": u.id,
            "access_code": u.access_code,
            "display_name": u.display_name,
            "expires_at": u.expires_at,
            "days_left": u.days_left,
            "active": bool(u.active),
            "expired": u.expired,
            "created_at": u.created_at,
            "last_login_at": u.last_login_at,
        }
        for u in auth_store.list_users()
    ]
    return jsonify({"ok": True, "users": users})


@app.route("/api/admin/users", methods=["POST"])
@admin_required
def api_admin_create_user():
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("display_name") or "").strip()
    months = int(payload.get("months") or 1)
    if not name:
        return jsonify({"ok": False, "error": "اكتب اسم المستخدم"}), 400
    try:
        user = auth_store.create_user(name, months=months)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify(
        {
            "ok": True,
            "user": {
                "id": user.id,
                "access_code": user.access_code,
                "display_name": user.display_name,
                "expires_at": user.expires_at,
                "days_left": user.days_left,
            },
        }
    )


@app.route("/api/ai/parse", methods=["POST"])
@login_required
def api_ai_parse():
    """يلصق نص التقرير → يملأ الغلاف والملاحظات عبر Gemini أو محلياً."""
    payload = request.get_json(force=True, silent=True) or {}
    raw = (payload.get("text") or "").strip()
    force_local = bool(payload.get("local_only"))
    if not raw:
        return jsonify({"ok": False, "error": "الصق النص أولاً"}), 400
    try:
        import ai_parse

        result = ai_parse.parse_report_text(raw, prefer_gemini=not force_local)
        # فرض تاريخ اليوم إذا طلب المستخدم ذلك أو كان فارغاً
        if payload.get("use_today_date", True) or not result["cover"].get("date"):
            from report_engine import today_date_str

            result["cover"]["date"] = today_date_str()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, **result})


@app.route("/api/admin/gemini-key", methods=["GET", "POST"])
@admin_required
def api_admin_gemini_key():
    import ai_parse

    if request.method == "GET":
        key = ai_parse.get_gemini_api_key()
        masked = (key[:4] + "…" + key[-4:]) if len(key) > 8 else ("مضبوط" if key else "")
        return jsonify({"ok": True, "configured": bool(key), "masked": masked})

    payload = request.get_json(force=True, silent=True) or {}
    key = (payload.get("api_key") or "").strip()
    ai_parse.set_gemini_api_key(key)
    return jsonify({"ok": True, "configured": bool(key)})


@app.route("/api/admin/users/<int:user_id>/renew", methods=["POST"])
@admin_required
def api_admin_renew(user_id: int):
    payload = request.get_json(force=True, silent=True) or {}
    months = int(payload.get("months") or 1)
    user = auth_store.renew_user(user_id, months=months)
    if not user:
        return jsonify({"ok": False, "error": "المستخدم غير موجود"}), 404
    return jsonify({"ok": True, "expires_at": user.expires_at, "days_left": user.days_left})


@app.route("/api/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def api_admin_toggle(user_id: int):
    user = auth_store.get_user_by_id(user_id)
    if not user:
        return jsonify({"ok": False, "error": "المستخدم غير موجود"}), 404
    auth_store.set_user_active(user_id, not bool(user.active))
    return jsonify({"ok": True, "active": not bool(user.active)})


@app.route("/api/admin/reset-user-report/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_reset_report(user_id: int):
    """يعيد نسخة المستخدم لقالب نظيف (أول استخدام من جديد)."""
    import shutil

    user = auth_store.get_user_by_id(user_id)
    if not user:
        return jsonify({"ok": False, "error": "المستخدم غير موجود"}), 404
    master = auth_store.master_template_path()
    if not master:
        return jsonify({"ok": False, "error": "لا يوجد قالب رئيسي"}), 500
    report = user.workspace / "report.pptx"
    user.workspace.mkdir(parents=True, exist_ok=True)
    shutil.copy2(master, report)
    PHOTO_STORES.pop(user_id, None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    auth_store.init_db()
    auth_store.master_template_path()
    port = int(os.environ.get("PORT", "5055"))
    print("=" * 56)
    print(" محرر التقارير الفنية — اشتراك شهري")
    print(f" دخول المستخدم:  http://127.0.0.1:{port}/login")
    print(f" لوحة الإدارة:   http://127.0.0.1:{port}/admin/login")
    print(f" كلمة مرور الأدمن الافتراضية: {auth_store.DEFAULT_ADMIN_PASSWORD}")
    print("=" * 56)
    app.run(host="0.0.0.0", port=port, debug=False)
