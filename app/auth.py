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
from werkzeug.security import check_password_hash, generate_password_hash

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


# ---------- 账户页：改密码 / 个性签名 ----------

@bp.route("/me", methods=("GET",))
@login_required
def account():
    user = current_user()
    return render_template("auth/account.html", user=user)


@bp.route("/me/password", methods=("POST",))
@login_required
def change_password():
    old = request.form.get("old_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (current_user()["id"],)).fetchone()
    if not check_password_hash(user["password_hash"], old):
        flash("旧密码不正确。", "danger")
    elif len(new) < 6:
        flash("新密码至少 6 位。", "danger")
    elif new != confirm:
        flash("两次输入的新密码不一致。", "danger")
    elif old == new:
        flash("新密码不能与旧密码相同。", "warning")
    else:
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new, method="pbkdf2:sha256"), user["id"]),
        )
        db.commit()
        flash("登录密码已修改。", "success")
    return redirect(url_for("auth.account"))


@bp.route("/me/signature", methods=("POST",))
@login_required
def change_signature():
    signature = request.form.get("signature", "").strip()
    if len(signature) > 50:
        flash("个性签名不能超过 50 字。", "danger")
    else:
        db = get_db()
        db.execute("UPDATE users SET signature=? WHERE id=?", (signature, current_user()["id"]))
        db.commit()
        flash("个性签名已保存。" if signature else "个性签名已清空。", "success")
    return redirect(url_for("auth.account"))
