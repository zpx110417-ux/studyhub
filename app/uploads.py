"""图片 / 附件上传与下载。

安全措施：登录 + 未封禁才能上传；扩展名白名单；图片用 Pillow 校验真实格式
（防改后缀伪装）；存储文件名用 uuid4 重命名（用户文件名只存库做展示）；
下载统一走 send_from_directory（自带防目录穿越）。
"""
import io
import os
import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    request,
    send_from_directory,
)
from PIL import Image

from .db import get_db
from .helpers import current_user, get_active_ban

bp = Blueprint("uploads", __name__)


def _api_user():
    """上传接口由前端 fetch 调用，校验失败返回 JSON 而非重定向。"""
    user = current_user()
    if user is None:
        return None, (jsonify({"error": "请先登录"}), 401)
    if get_active_ban(user["id"]) is not None:
        return None, (jsonify({"error": "账号已被封禁，无法上传"}), 403)
    return user, None


def _save_upload(fileobj, allowed_exts, is_image):
    """校验并保存上传文件，返回 ((stored, ext, size, orig_name), None) 或 (None, 错误)。"""
    orig = fileobj.filename or ""
    ext = os.path.splitext(orig)[1].lower().lstrip(".")
    if ext not in allowed_exts:
        return None, f"不支持的文件类型：.{ext or '（无后缀）'}"
    data = fileobj.read()
    if not data:
        return None, "文件为空。"
    if is_image:
        try:
            Image.open(io.BytesIO(data)).verify()  # 校验真实格式，防伪装后缀
        except Exception:
            return None, "文件不是有效的图片。"
    stored = uuid.uuid4().hex + "." + ext
    with open(os.path.join(current_app.config["UPLOAD_DIR"], stored), "wb") as f:
        f.write(data)
    return (stored, ext, len(data), orig), None


@bp.route("/upload/image", methods=("POST",))
def upload_image():
    user, err = _api_user()
    if err:
        return err
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "未选择文件"}), 400
    result, error = _save_upload(f, current_app.config["ALLOWED_IMAGE_EXTS"], is_image=True)
    if error:
        return jsonify({"error": error}), 400
    stored, ext, size, orig = result
    db = get_db()
    db.execute(
        "INSERT INTO files (uploader_id, orig_name, stored_name, ext, size, is_image) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (user["id"], orig, stored, ext, size),
    )
    db.commit()
    return jsonify({"markdown": f"![{orig}](/files/{stored})", "url": f"/files/{stored}"})


@bp.route("/upload/file", methods=("POST",))
def upload_file():
    user, err = _api_user()
    if err:
        return err
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "未选择文件"}), 400
    result, error = _save_upload(f, current_app.config["ALLOWED_FILE_EXTS"], is_image=False)
    if error:
        return jsonify({"error": error}), 400
    stored, ext, size, orig = result
    db = get_db()
    db.execute(
        "INSERT INTO files (uploader_id, orig_name, stored_name, ext, size, is_image) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (user["id"], orig, stored, ext, size),
    )
    db.commit()
    return jsonify({"markdown": f"[{orig}](/files/{stored})", "url": f"/files/{stored}"})


@bp.route("/files/<stored_name>")
def download(stored_name):
    row = get_db().execute(
        "SELECT * FROM files WHERE stored_name=?", (stored_name,)
    ).fetchone()
    if row is None:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"],
        stored_name,
        download_name=row["orig_name"],
        as_attachment=not row["is_image"],
    )
