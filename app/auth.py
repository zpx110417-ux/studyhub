"""用户认证：登录 / 登出 / 封禁提示页。（注册通道已关闭，账号由管理员导入成员名单统一创建）"""
from datetime import datetime

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from .db import get_db
from .helpers import current_user, get_active_ban, login_required

bp = Blueprint("auth", __name__)


@bp.route("/auth/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            # 统一提示，不透露用户名是否存在
            flash("用户名或密码错误。", "danger")
        else:
            session.clear()  # 防会话固定
            session["user_id"] = user["id"]
            # 封禁中的账号登录后只能看到封禁提示页
            if get_active_ban(user["id"]) is not None:
                return redirect(url_for("auth.banned"))
            flash(f"欢迎回来，{user['username']}！", "success")
            nxt = request.form.get("next") or url_for("wiki.index")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("wiki.index")
            return redirect(nxt)
    return render_template("auth/login.html", next=request.args.get("next", ""))


def _remaining_text(until_str):
    """把封禁截止时间换算成"还剩 X 天 X 小时 X 分钟"的可读文案。"""
    try:
        until = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return until_str
    secs = int((until - datetime.now()).total_seconds())
    if secs <= 0:
        return "不足 1 分钟"
    days, rest = divmod(secs, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    parts.append(f"{minutes} 分钟")
    return " ".join(parts)


@bp.route("/banned")
@login_required
def banned():
    """封禁提示页：封禁账号唯一可见的页面（除申诉页）。"""
    from config import APPEAL_MAX_PER_BAN

    ban = get_active_ban(current_user()["id"])
    if ban is None:
        return redirect(url_for("wiki.index"))
    banner = get_db().execute(
        "SELECT username FROM users WHERE id=?", (ban["banned_by"],)
    ).fetchone()
    return render_template(
        "banned.html", ban=ban, remaining=_remaining_text(ban["banned_until"]),
        banner_name=banner["username"] if banner else "管理员",
        max_appeals=APPEAL_MAX_PER_BAN,
    )


@bp.route("/auth/logout", methods=("POST",))
def logout():
    session.clear()
    flash("已退出登录。", "success")
    return redirect(url_for("wiki.index"))
