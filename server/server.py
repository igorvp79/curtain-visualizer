"""
Белая Река · QR-загрузка фото с телефона
Простой Flask-сервер для Render.com.

Логика:
- Визуализатор: POST /session → создаёт сессию, получает session_id
- Телефон: POST /upload/<session_id> → загружает файл (multipart/form-data, поле "image")
- Визуализатор: GET /photo/<session_id> → возвращает url фото когда оно загрузилось
- Любой: GET /ping → keepalive (чтобы разбудить службу заранее)

Хранение — в памяти процесса. Сессии истекают через 15 минут.
Файлы тоже храним в памяти (как base64 dataURL), отдаём напрямую визуализатору.
Этого достаточно, потому что фото нужно ровно один раз и сразу.
"""

import os
import io
import time
import uuid
import base64
import threading
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from PIL import Image

app = Flask(__name__)
# CORS открыт всем — у нас публичный API без секретных данных.
# Явно разрешаем все методы и заголовки, чтобы preflight OPTIONS-запросы получали правильный ответ.
CORS(app,
     resources={r"/*": {"origins": "*"}},
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     supports_credentials=False)


# Дополнительный страховочный обработчик OPTIONS для любого маршрута.
# Это гарантирует, что preflight-запрос с любым Content-Type получит 204 No Content + CORS-заголовки.
@app.after_request
def add_cors_headers(response):
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
        "version": "1.0"
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


@app.route('/upload/<session_id>', methods=['POST', 'OPTIONS'])
def upload_photo(session_id):
    """Телефон загружает фото в указанную сессию."""
    if request.method == 'OPTIONS':
        return '', 204

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


@app.route('/share', methods=['POST', 'OPTIONS'])
def create_share():
    """Дизайнер шлёт готовое изображение, получает share_id для QR."""
    if request.method == 'OPTIONS':
        return '', 204

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


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
