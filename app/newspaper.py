"""报刊模块：朋友圈式的实名/匿名分享流，支持点赞、评论、举报。

发帖与评论均受高危词实时拦截与中危词系统识别监管；
管理员删除帖子/评论必须给出理由，并公开公示（deletions 表，target_type=post/post_comment）。
"""
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .db import get_db
from .helpers import current_user, write_required
from .markdown_render import render_md
from .moderation import check_high, flag_low

bp = Blueprint("newspaper", __name__)


def _visible_condition(is_admin):
    """公开流只展示 visible 内容；管理员在列表中额外标记被隐藏帖。"""
    return "p.status='visible'" if not is_admin else "1=1"


@bp.route("/newspaper", methods=("GET",))
def index():
    db = get_db()
    user = current_user()
    is_admin = bool(user and user["role"] == "admin")
    posts = db.execute(
        "SELECT p.*, u.username AS author, u.signature AS author_signature, "
        "(SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS n_likes, "
        "(SELECT COUNT(*) FROM post_comments c WHERE c.post_id=p.id AND c.status='visible') AS n_comments, "
        "EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked_by_me "
        "FROM posts p JOIN users u ON u.id=p.author_id "
        f"WHERE {_visible_condition(is_admin)} ORDER BY p.created_at DESC LIMIT 50",
        (user["id"] if user else 0,),
    ).fetchall()
    # 一次取回这些帖子的可见评论
    comments = {}
    if posts:
        ids = [str(p["id"]) for p in posts]
        rows = db.execute(
            "SELECT c.*, u.username AS author FROM post_comments c "
            "JOIN users u ON u.id=c.author_id "
            f"WHERE c.post_id IN ({','.join(ids)}) AND c.status='visible' ORDER BY c.id"
        ).fetchall()
        for c in rows:
            comments.setdefault(c["post_id"], []).append(c)
    return render_template(
        "newspaper.html", posts=posts, comments=comments, is_admin=is_admin,
    )


@bp.route("/newspaper/post", methods=("POST",))
@write_required
def create():
    content = request.form.get("content", "").strip()
    anonymous = 1 if request.form.get("anonymous") == "1" else 0
    if not content:
        flash("发布内容不能为空。", "danger")
        return redirect(url_for("newspaper.index"))
    if len(content) > 5000:
        flash("发布内容过长（上限 5000 字）。", "danger")
        return redirect(url_for("newspaper.index"))
    db = get_db()
    error = check_high(content)
    if error:
        flash(error, "danger")
        return redirect(url_for("newspaper.index"))
    user_id = current_user()["id"]
    cur = db.execute(
        "INSERT INTO posts (author_id, anonymous, content_md, content_html) VALUES (?, ?, ?, ?)",
        (user_id, anonymous, content, render_md(content)),
    )
    flag_low(content, user_id, post_id=cur.lastrowid)
    db.commit()
    flash("已发布到报刊。", "success")
    return redirect(url_for("newspaper.index"))


@bp.route("/newspaper/<int:post_id>/like", methods=("POST",))
@write_required
def like(post_id):
    db = get_db()
    if db.execute(
        "SELECT 1 FROM posts WHERE id=? AND status='visible'", (post_id,)
    ).fetchone() is None:
        abort(404)
    user_id = current_user()["id"]
    if db.execute(
        "SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?", (post_id, user_id)
    ).fetchone():
        db.execute("DELETE FROM post_likes WHERE post_id=? AND user_id=?", (post_id, user_id))
        flash("已取消点赞。", "success")
    else:
        db.execute("INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)", (post_id, user_id))
        flash("已点赞。", "success")
    db.commit()
    return redirect(url_for("newspaper.index"))


@bp.route("/newspaper/<int:post_id>/comment", methods=("POST",))
@write_required
def comment(post_id):
    db = get_db()
    if db.execute(
        "SELECT 1 FROM posts WHERE id=? AND status='visible'", (post_id,)
    ).fetchone() is None:
        abort(404)
    content = request.form.get("content", "").strip()
    if not content:
        flash("评论内容不能为空。", "danger")
        return redirect(url_for("newspaper.index"))
    if len(content) > 1000:
        flash("评论内容请控制在 1000 字以内。", "danger")
        return redirect(url_for("newspaper.index"))
    error = check_high(content)
    if error:
        flash(error, "danger")
        return redirect(url_for("newspaper.index"))
    user_id = current_user()["id"]
    cur = db.execute(
        "INSERT INTO post_comments (post_id, author_id, content_md, content_html) VALUES (?, ?, ?, ?)",
        (post_id, user_id, content, render_md(content)),
    )
    flag_low(content, user_id, post_comment_id=cur.lastrowid)
    db.commit()
    flash("评论已发布。", "success")
    return redirect(url_for("newspaper.index"))
