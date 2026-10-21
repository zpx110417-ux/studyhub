"""问答模块：提问 / 回答 / 关闭（免审批直接发布，受敏感词检测与举报监管）。"""
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

bp = Blueprint("qa", __name__)


@bp.route("/qa")
def list_questions():
    rows = get_db().execute(
        "SELECT q.id, q.title, q.status, q.created_at, u.username AS author, "
        "(SELECT COUNT(*) FROM answers a WHERE a.question_id=q.id AND a.status='visible') AS n_answers "
        "FROM questions q JOIN users u ON u.id=q.author_id "
        "WHERE q.status!='hidden' ORDER BY q.created_at DESC LIMIT 100"
    ).fetchall()
    return render_template("qa/list.html", questions=rows)


@bp.route("/qa/new", methods=("GET", "POST"))
@write_required
def new_question():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "")
        if not title or not content.strip():
            flash("标题和内容不能为空。", "danger")
        else:
            db = get_db()
            error = check_high(f"{title}\n{content}")
            if error:
                flash(error, "danger")
            else:
                user_id = current_user()["id"]
                cur = db.execute(
                    "INSERT INTO questions (author_id, title, content_md, content_html) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, title, content, render_md(content)),
                )
                flag_low(f"{title}\n{content}", user_id, question_id=cur.lastrowid)
                db.commit()
                flash("提问已发布。", "success")
                return redirect(url_for("qa.detail", question_id=cur.lastrowid))
    return render_template("qa/new.html", title="", content="")


@bp.route("/qa/<int:question_id>")
def detail(question_id):
    db = get_db()
    q = db.execute(
        "SELECT q.*, u.username AS author FROM questions q "
        "JOIN users u ON u.id=q.author_id WHERE q.id=?",
        (question_id,),
    ).fetchone()
    if q is None:
        abort(404)
    user = current_user()
    is_owner = user is not None and (user["role"] == "admin" or q["author_id"] == user["id"])
    if q["status"] == "hidden" and not is_owner:
        abort(404)
    answers = db.execute(
        "SELECT a.*, u.username AS author FROM answers a "
        "JOIN users u ON u.id=a.author_id WHERE a.question_id=? "
        "AND (a.status='visible' OR ?) ORDER BY a.id",
        (question_id, 1 if is_owner else 0),
    ).fetchall()
    return render_template("qa/detail.html", q=q, answers=answers, is_owner=is_owner)


@bp.route("/qa/<int:question_id>/answer", methods=("POST",))
@write_required
def answer(question_id):
    db = get_db()
    q = db.execute(
        "SELECT * FROM questions WHERE id=? AND status='open'", (question_id,)
    ).fetchone()
    if q is None:
        abort(404)
    content = request.form.get("content", "").strip()
    if not content:
        flash("回答内容不能为空。", "danger")
    else:
        error = check_high(content)
        if error:
            flash(error, "danger")
        else:
            user_id = current_user()["id"]
            cur = db.execute(
                "INSERT INTO answers (question_id, author_id, content_md, content_html) "
                "VALUES (?, ?, ?, ?)",
                (question_id, user_id, content, render_md(content)),
            )
            flag_low(content, user_id, question_id=question_id, answer_id=cur.lastrowid)
            db.commit()
            flash("回答已发布。", "success")
    return redirect(url_for("qa.detail", question_id=question_id))


@bp.route("/qa/<int:question_id>/close", methods=("POST",))
@write_required
def close(question_id):
    db = get_db()
    q = db.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if q is None:
        abort(404)
    user = current_user()
    if user["role"] != "admin" and q["author_id"] != user["id"]:
        abort(403)
    new_status = "open" if q["status"] == "closed" else "closed"
    db.execute("UPDATE questions SET status=? WHERE id=?", (new_status, question_id))
    db.commit()
    flash("问题已关闭。" if new_status == "closed" else "问题已重新开放。", "success")
    return redirect(url_for("qa.detail", question_id=question_id))
