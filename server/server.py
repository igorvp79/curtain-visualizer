"""
Белая Река · QR-загрузка фото с телефона + сбор работ на почту
Простой Flask-сервер для Render.com.

Логика:
- Визуализатор: POST /session → создаёт сессию, получает session_id
- Телефон: POST /upload/<session_id> → загружает файл (multipart/form-data, поле "image")
- Визуализатор: GET /photo/<session_id> → возвращает url фото когда оно загрузилось
- Дизайнер: POST /share → шлёт готовое фото, получает share_id для QR
- Клиент: GET /view/<share_id> → получает фото по share_id
- Визуализатор: POST /collect → тихо присылает владельцу на почту копию
                                 скачанной пользователем работы (обратная связь)
- Любой: GET /ping → keepalive (чтобы разбудить службу заранее)

Хранение сессий/шар — в памяти процесса (на free-тарифе Render это ок,
т.к. данные нужны один раз и сразу). Работы НЕ хранятся на сервере —
они сразу уходят письмом на почту владельцу.
"""

import os
import io
import ssl
import time
import uuid
import base64
import smtplib
import threading
from datetime import datetime
from email.message import EmailMessage

from flask import Flask, request, jsonify, abort, make_response
from PIL import Image

app = Flask(__name__)


# =========================================
# CORS — чистая ручная реализация без flask-cors
# (с flask-cors были проблемы на preflight для /share)
# =========================================
@app.before_request
def handle_preflight():
    """Любой OPTIONS-запрос отвечаем сразу 204 с CORS-заголовками."""
    if request.method == 'OPTIONS':
        resp = make_response('', 204)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        resp.headers['Access-Control-Max-Age'] = '3600'
        return resp


@app.after_request
def add_cors_headers(response):
    """На все ответы добавляем CORS-заголовки."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return response

# Хранилище сессий: session_id -> {"created": ts, "photo_url": None | "data:image/jpeg;base64,..."}
sessions = {}
sessions_lock = threading.Lock()

SESSION_TTL_SECONDS = 15 * 60   # 15 минут
MAX_IMAGE_SIDE = 1920           # сжимаем до 1920 по большей стороне
JPEG_QUALITY = 85


def cleanup_old_sessions():
    """Фоновая очистка сессий старше TTL."""
    now = time.time()
    with sessions_lock:
        expired = [sid for sid, s in sessions.items() if now - s["created"] > SESSION_TTL_SECONDS]
        for sid in expired:
            del sessions[sid]


@app.route('/')
def root():
    return jsonify({
        "service": "belaya-reka-photo-bridge",
        "status": "ok",
        "version": "1.1"
    })


@app.route('/ping')
def ping():
    """Используется для пробуждения сервера на Render free tier."""
    return jsonify({"pong": True, "ts": int(time.time())})


@app.route('/session', methods=['POST'])
def create_session():
    """Визуализатор создаёт новую сессию и получает session_id."""
    cleanup_old_sessions()
    session_id = uuid.uuid4().hex[:12]  # 12 символов, безопасно и компактно
    with sessions_lock:
        sessions[session_id] = {
            "created": time.time(),
            "photo_url": None,
        }
    return jsonify({"session_id": session_id})


@app.route('/upload/<session_id>', methods=['POST'])
def upload_photo(session_id):
    """Телефон загружает фото в указанную сессию."""
    with sessions_lock:
        if session_id not in sessions:
            return jsonify({"error": "session not found or expired"}), 404

    if 'image' not in request.files:
        return jsonify({"error": "no 'image' field in form"}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "empty filename"}), 400

    try:
        # Открываем картинку и пересжимаем
        img = Image.open(file.stream)
        # Поворачиваем по EXIF (iPhone часто кладёт ориентацию в EXIF)
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Конвертируем в RGB (на случай PNG с альфой / HEIC)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Уменьшаем, если больше лимита
        w, h = img.size
        if max(w, h) > MAX_IMAGE_SIDE:
            if w >= h:
                new_w = MAX_IMAGE_SIDE
                new_h = int(h * MAX_IMAGE_SIDE / w)
            else:
                new_h = MAX_IMAGE_SIDE
                new_w = int(w * MAX_IMAGE_SIDE / h)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Кодируем в JPEG → base64 dataURL
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        data_url = f"data:image/jpeg;base64,{b64}"

    except Exception as e:
        return jsonify({"error": f"image processing failed: {e}"}), 400

    with sessions_lock:
        if session_id not in sessions:
            return jsonify({"error": "session expired during upload"}), 404
        sessions[session_id]["photo_url"] = data_url

    return jsonify({"ok": True, "size_bytes": len(b64)})


@app.route('/photo/<session_id>', methods=['GET'])
def get_photo(session_id):
    """Визуализатор поллит этот endpoint, пока не появится photo_url."""
    with sessions_lock:
        if session_id not in sessions:
            return jsonify({"status": "not_found"}), 404
        s = sessions[session_id]
        if s["photo_url"] is None:
            return jsonify({"status": "waiting"})
        # Когда отдали фото — удаляем сессию (одноразовая)
        photo_url = s["photo_url"]
        del sessions[session_id]
        return jsonify({"status": "ready", "photo_url": photo_url})


# =========================================
# ОБРАТНАЯ ПЕРЕДАЧА: дизайнер → клиент
# =========================================
# Дизайнер шлёт готовое фото на /share → получает share_id
# Клиент по QR открывает /view/<share_id> на view.html → видит фото

# Хранилище: share_id -> {"created": ts, "data_url": "..."}
shares = {}
shares_lock = threading.Lock()
SHARE_TTL_SECONDS = 60 * 60  # 1 час


def cleanup_old_shares():
    now = time.time()
    with shares_lock:
        expired = [sid for sid, s in shares.items() if now - s["created"] > SHARE_TTL_SECONDS]
        for sid in expired:
            del shares[sid]


@app.route('/share', methods=['POST'])
def create_share():
    """Дизайнер шлёт готовое изображение, получает share_id для QR."""
    cleanup_old_shares()

    data = request.get_json(silent=True) or {}
    data_url = data.get('image')
    if not data_url or not data_url.startswith('data:image/'):
        return jsonify({"error": "no valid 'image' (data URL) in JSON body"}), 400

    # Защита от слишком больших файлов — лимит 10 МБ в base64 (~7.5 МБ бинарных данных)
    if len(data_url) > 10 * 1024 * 1024:
        return jsonify({"error": "image too large"}), 413

    share_id = uuid.uuid4().hex[:12]
    with shares_lock:
        shares[share_id] = {
            "created": time.time(),
            "data_url": data_url,
        }

    return jsonify({"share_id": share_id})


@app.route('/view/<share_id>', methods=['GET'])
def get_share(share_id):
    """Клиент (страница view.html) получает картинку по share_id."""
    cleanup_old_shares()
    with shares_lock:
        if share_id not in shares:
            return jsonify({"status": "not_found"}), 404
        return jsonify({"status": "ok", "data_url": shares[share_id]["data_url"]})


# =========================================
# СБОР РАБОТ НА ПОЧТУ ВЛАДЕЛЬЦА
# =========================================
# При нажатии "Скачать результат" в визуализаторе страница тихо шлёт сюда
# копию картинки, а сервер пересылает её письмом на MAIL_TO.
# Ничего на сервере не хранится — только пересылка.
#
# Настройки берутся из переменных окружения (Render → Environment),
# чтобы пароль не лежал в открытом коде на GitHub:
#   SMTP_HOST      напр. smtp.mail.ru
#   SMTP_PORT      напр. 465
#   SMTP_USER      напр. igorvp79@mail.ru   (от чьего имени шлём)
#   SMTP_PASSWORD  пароль для внешних приложений (НЕ обычный пароль почты)
#   MAIL_TO        куда слать (если не задано — на SMTP_USER)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.mail.ru")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MAIL_TO = os.environ.get("MAIL_TO", "") or SMTP_USER

# Лимит на входящую картинку (base64), чтобы не завалить память и почту
COLLECT_MAX_CHARS = 12 * 1024 * 1024  # ~9 МБ бинарных данных


def _send_work_email(png_bytes, when_str):
    """Отправляет одно письмо с картинкой во вложении. Вызывается в отдельном потоке."""
    if not (SMTP_USER and SMTP_PASSWORD and MAIL_TO):
        print("[collect] SMTP не настроен (нет SMTP_USER/SMTP_PASSWORD/MAIL_TO) — письмо не отправлено")
        return

    try:
        msg = EmailMessage()
        msg["Subject"] = f"Визуализатор штор — новая работа ({when_str})"
        msg["From"] = SMTP_USER
        msg["To"] = MAIL_TO
        msg.set_content(
            "Пользователь скачал результат в визуализаторе штор.\n"
            f"Время: {when_str}\n\n"
            "Картинка во вложении."
        )
        filename = "belaya-reka-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".png"
        msg.add_attachment(png_bytes, maintype="image", subtype="png", filename=filename)

        context = ssl.create_default_context()
        # Порт 465 → SSL; порт 587 → STARTTLS
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.starttls(context=context)
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

        print(f"[collect] письмо отправлено на {MAIL_TO}")
    except Exception as e:
        # Не роняем ничего — просто логируем, пользователь этого не видит
        print(f"[collect] ошибка отправки письма: {e}")


@app.route('/collect', methods=['POST'])
def collect_work():
    """Страница тихо шлёт сюда скачанную работу — пересылаем её на почту владельцу."""
    data = request.get_json(silent=True) or {}
    data_url = data.get('image')
    if not data_url or not data_url.startswith('data:image/'):
        return jsonify({"error": "no valid 'image' (data URL) in JSON body"}), 400

    if len(data_url) > COLLECT_MAX_CHARS:
        return jsonify({"error": "image too large"}), 413

    # Достаём чистый base64 после запятой и декодируем
    try:
        b64 = data_url.split(',', 1)[1]
        png_bytes = base64.b64decode(b64)
    except Exception:
        return jsonify({"error": "cannot decode image"}), 400

    when_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Отправляем письмо в фоне, чтобы страница не ждала (Render free бывает медленным)
    threading.Thread(target=_send_work_email, args=(png_bytes, when_str), daemon=True).start()

    # Сразу отвечаем ок — доставка письма идёт в фоне
    return jsonify({"ok": True})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
