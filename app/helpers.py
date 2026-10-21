"""公共工具：当前用户、权限装饰器、CSRF、站点设置、封禁查询、编辑权限判定。"""
import functools
import secrets

from flask import abort, flash, g, redirect, request, session, url_for

from .db import get_db


# ---------- 当前用户 ----------

def current_user():
    """从 session 解析当前登录用户，每请求只查一次库；未登录返回 None。"""
    if "user" in g:
        return g.user
    g.user = None
    uid = session.get("user_id")
    if uid is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return g.user


# ---------- 在线人数（10 分钟内有过请求的登录用户） ----------

ACTIVE_WINDOW_MINUTES = 10


def touch_active():
    """登录用户每次请求时刷新最后活跃时间；跳过静态资源。"""
    user = current_user()
    if user is None:
        return
    if request.endpoint == "static":
        return
    get_db().execute(
        "UPDATE users SET last_active_at=datetime('now','localtime') WHERE id=?",
        (user["id"],),
    )
    get_db().commit()


def online_users():
    """最近 10 分钟内活跃的登录用户，按最后活跃倒序。"""
    return get_db().execute(
        "SELECT username, role, last_active_at FROM users "
        f"WHERE last_active_at > datetime('now', '-{ACTIVE_WINDOW_MINUTES} minutes', 'localtime') "
        "ORDER BY last_active_at DESC"
    ).fetchall()


# ---------- 封禁（小黑屋） ----------

def get_active_ban(user_id):
    """用户当前生效中的封禁记录（可能为 None）；每请求只查一次库。"""
    if "active_ban" in g:
        return g.active_ban if g.active_ban_id == user_id else None
    g.active_ban_id = user_id
    g.active_ban = get_db().execute(
        "SELECT * FROM bans WHERE user_id=? AND lifted_at IS NULL "
        "AND banned_until > datetime('now','localtime') "
        "ORDER BY banned_until DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return g.active_ban


# ---------- 访问装饰器 ----------

def login_required(view):
    """需要登录（封禁用户也可访问：用于浏览、申诉等）。"""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("请先登录。", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def write_required(view):
    """登录 + 未被封禁：封禁用户一切页面都被拦截（见 __init__.py 的 banned_gate），
    此处作为第二道防线，防止封禁用户提交写操作。"""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("请先登录。", "warning")
            return redirect(url_for("auth.login", next=request.path))
        ban = get_active_ban(user["id"])
        if ban is not None:
            flash("您的账号处于封禁状态，无法进行该操作。", "danger")
            return redirect(url_for("auth.banned"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """需要管理员角色。"""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("请先登录。", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


# ---------- CSRF ----------

def generate_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


# ---------- 站点设置 ----------

def get_setting(key, default=""):
    row = get_db().execute(
        "SELECT value FROM site_settings WHERE key=?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    """写入设置（不自动 commit，由调用方统一提交事务）。"""
    get_db().execute(
        "INSERT INTO site_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ---------- 页面编辑权限（全站唯一判定入口） ----------

def get_edit_grant(user_id, page_id):
    """未过期的编辑授权记录（可能为 None）。"""
    return get_db().execute(
        "SELECT * FROM edit_requests WHERE requester_id=? AND page_id=? "
        "AND status='approved' AND expires_at > datetime('now','localtime')",
        (user_id, page_id),
    ).fetchone()


def get_pending_request(user_id, page_id):
    """待审的编辑权申请记录（可能为 None）。"""
    return get_db().execute(
        "SELECT * FROM edit_requests WHERE requester_id=? AND page_id=? AND status='pending'",
        (user_id, page_id),
    ).fetchone()


def can_edit(page, user):
    """判定 user 能否编辑 page：
    1. 管理员 → 可以；
    2. 页面作者 → 永远可以（即使被封禁前的授权被撤销也不影响自己的页面）；
    3. 其他用户 → 需有该页面的、未过期的授权（批准后 24 小时内有效）。
    """
    if user is None:
        return False
    if user["role"] == "admin":
        return True
    if page["author_id"] == user["id"]:
        return True
    return get_edit_grant(user["id"], page["id"]) is not None
