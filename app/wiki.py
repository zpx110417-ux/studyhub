"""学习库页面：首页 / 浏览 / 创建（审批制）/ 编辑 / 版本 / 编辑权申请 / 搜索 / 举报 / 申诉 / 规则。"""
import difflib

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from config import APPEAL_MAX_PER_BAN
from .db import get_db
from .helpers import (
    can_edit,
    current_user,
    get_active_ban,
    get_edit_grant,
    get_pending_request,
    get_setting,
    login_required,
    write_required,
)
from .markdown_render import render_md
from .moderation import check_high, flag_low

bp = Blueprint("wiki", __name__)


# ---------- 可见性工具 ----------

def _get_visible_page(page_id):
    """已发布对所有人可见；待审/被驳回/被隐藏仅作者和管理员可见，其余按 404 处理。"""
    page = get_db().execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    if page is None:
        abort(404)
    user = current_user()
    if page["status"] == "published":
        return page
    if user and (user["role"] == "admin" or page["author_id"] == user["id"]):
        return page
    abort(404)


def _random_admin_id(db):
    row = db.execute(
        "SELECT id FROM users WHERE role='admin' ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


# ---------- 首页 ----------

@bp.route("/")
def index():
    db = get_db()
    pages = db.execute(
        "SELECT p.id, p.title, p.updated_at, u.username AS author FROM pages p "
        "JOIN users u ON u.id=p.author_id WHERE p.status='published' "
        "ORDER BY p.updated_at DESC LIMIT 10"
    ).fetchall()
    questions = db.execute(
        "SELECT q.id, q.title, q.created_at, u.username AS author, "
        "(SELECT COUNT(*) FROM answers a WHERE a.question_id=q.id AND a.status='visible') AS n_answers "
        "FROM questions q JOIN users u ON u.id=q.author_id "
        "WHERE q.status!='hidden' ORDER BY q.created_at DESC LIMIT 5"
    ).fetchall()
    return render_template("index.html", pages=pages, questions=questions)


# ---------- 页面浏览 ----------

@bp.route("/wiki/<int:page_id>")
def view(page_id):
    page = _get_visible_page(page_id)
    user = current_user()
    db = get_db()
    author = db.execute(
        "SELECT username FROM users WHERE id=?", (page["author_id"],)
    ).fetchone()
    reviewer_name = None
    if page["reviewed_by"]:
        row = db.execute(
            "SELECT username FROM users WHERE id=?", (page["reviewed_by"],)
        ).fetchone()
        reviewer_name = row["username"] if row else None
    editable = can_edit(page, user)
    grant = pending_req = None
    if user and not editable and page["status"] == "published":
        grant = get_edit_grant(user["id"], page_id)  # 过期授权（用于提示）
        pending_req = get_pending_request(user["id"], page_id)
    return render_template(
        "wiki/view.html", page=page, author=author["username"],
        editable=editable, grant=grant, pending_req=pending_req,
        reviewer_name=reviewer_name,
    )


# ---------- 创建页面（审批制） ----------

@bp.route("/wiki/new", methods=("GET", "POST"))
@write_required
def new():
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
                    "INSERT INTO pages (title, content_md, content_html, author_id, status, reviewed_by) "
                    "VALUES (?, ?, ?, ?, 'pending', ?)",
                    (title, content, render_md(content), user_id, _random_admin_id(db)),
                )
                page_id = cur.lastrowid
                db.execute(
                    "INSERT INTO page_versions (page_id, editor_id, title, content_md, comment) "
                    "VALUES (?, ?, ?, ?, '创建页面')",
                    (page_id, user_id, title, content),
                )
                flag_low(f"{title}\n{content}", user_id, page_id=page_id)
                db.commit()
                flash("页面已提交，等待管理员审批（24 小时内未处理将由系统自动判定）。", "success")
                return redirect(url_for("wiki.view", page_id=page_id))
    return render_template(
        "wiki/edit.html", page=None, title="", content="", comment="",
        action="new", reject_locked=False,
    )


# ---------- 编辑页面 ----------

@bp.route("/wiki/<int:page_id>/edit", methods=("GET", "POST"))
@write_required
def edit(page_id):
    db = get_db()
    page = db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    if page is None:
        abort(404)
    user = current_user()

    # 待审 / 被驳回 / 被隐藏的页面只有作者和管理员能进入编辑
    if page["status"] != "published" and user["role"] != "admin" \
            and page["author_id"] != user["id"]:
        abort(404)

    if not can_edit(page, user):
        flash("编辑他人创建的页面需要先申请编辑授权。", "warning")
        return redirect(url_for("wiki.apply_edit", page_id=page_id))

    is_author = page["author_id"] == user["id"]
    reject_locked = False
    today = db.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
    if is_author and page["status"] == "rejected":
        reject_locked = page["reject_count"] >= 3 and page["last_reject_date"] == today

    if request.method == "POST":
        if reject_locked:
            flash("该页面今天已被驳回 3 次，请明天再重新提交。", "danger")
            return redirect(url_for("wiki.view", page_id=page_id))
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "")
        comment = request.form.get("comment", "").strip()
        if not title or not content.strip():
            flash("标题和内容不能为空。", "danger")
        else:
            error = check_high(f"{title}\n{content}")
            if error:
                flash(error, "danger")
            else:
                # 修改前的内容存入版本表
                db.execute(
                    "INSERT INTO page_versions (page_id, editor_id, title, content_md, comment) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (page_id, user["id"], page["title"], page["content_md"], comment or "编辑"),
                )
                new_status = page["status"]
                reviewer_id = page["reviewed_by"]
                # 被驳回的页面由作者修改保存 → 重新进入待审（跨天重置连续驳回计数）
                if is_author and page["status"] == "rejected":
                    new_status = "pending"
                    if page["last_reject_date"] != today:
                        db.execute("UPDATE pages SET reject_count=0 WHERE id=?", (page_id,))
                    reviewer_id = _random_admin_id(db)
                db.execute(
                    "UPDATE pages SET title=?, content_md=?, content_html=?, "
                    "updated_at=datetime('now','localtime'), status=?, reviewed_by=? WHERE id=?",
                    (title, content, render_md(content), new_status, reviewer_id, page_id),
                )
                flag_low(f"{title}\n{content}", user["id"], page_id=page_id)
                db.commit()
                flash(
                    "已重新提交，等待管理员审批。" if new_status == "pending" else "保存成功。",
                    "success",
                )
                return redirect(url_for("wiki.view", page_id=page_id))
    return render_template(
        "wiki/edit.html", page=page, title=page["title"], content=page["content_md"],
        comment="", action="edit", reject_locked=reject_locked,
    )


# ---------- 版本历史 / 对比 / 回滚 ----------

@bp.route("/wiki/<int:page_id>/history")
def history(page_id):
    page = _get_visible_page(page_id)
    versions = get_db().execute(
        "SELECT v.id, v.editor_id, v.title, v.comment, v.edited_at, u.username AS editor "
        "FROM page_versions v JOIN users u ON u.id=v.editor_id "
        "WHERE v.page_id=? ORDER BY v.id DESC",
        (page_id,),
    ).fetchall()
    return render_template(
        "wiki/history.html", page=page, versions=versions,
        editable=can_edit(page, current_user()),
    )


@bp.route("/wiki/<int:page_id>/diff")
def diff(page_id):
    page = _get_visible_page(page_id)
    try:
        v_from = int(request.args.get("from", 0))
        v_to = int(request.args.get("to", 0))
    except (TypeError, ValueError):
        abort(404)
    rows = get_db().execute(
        "SELECT * FROM page_versions WHERE page_id=? AND id IN (?, ?)",
        (page_id, v_from, v_to),
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    if v_from not in by_id or v_to not in by_id:
        abort(404)
    diff_lines = list(difflib.ndiff(
        by_id[v_from]["content_md"].splitlines(),
        by_id[v_to]["content_md"].splitlines(),
    ))
    return render_template(
        "wiki/diff.html", page=page, v_from=by_id[v_from], v_to=by_id[v_to],
        diff_lines=diff_lines,
    )


@bp.route("/wiki/<int:page_id>/rollback", methods=("POST",))
@write_required
def rollback(page_id):
    db = get_db()
    page = db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    if page is None or page["status"] != "published":
        abort(404)
    if not can_edit(page, current_user()):
        abort(403)
    version = db.execute(
        "SELECT * FROM page_versions WHERE id=? AND page_id=?",
        (request.form.get("version_id", type=int) or 0, page_id),
    ).fetchone()
    if version is None:
        abort(404)
    user_id = current_user()["id"]
    # 当前内容先备份为新版本，再把指定版本内容恢复为页面现状（版本链不断）
    db.execute(
        "INSERT INTO page_versions (page_id, editor_id, title, content_md, comment) "
        "VALUES (?, ?, ?, ?, '回滚前自动备份')",
        (page_id, user_id, page["title"], page["content_md"]),
    )
    db.execute(
        "UPDATE pages SET title=?, content_md=?, content_html=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (version["title"], version["content_md"], render_md(version["content_md"]), page_id),
    )
    db.commit()
    flash(f"已回滚到版本 #{version['id']}（原内容已自动备份）。", "success")
    return redirect(url_for("wiki.view", page_id=page_id))


# ---------- 搜索 ----------

@bp.route("/search")
def search():
    q = request.args.get("q", "").strip()
    pages, questions = [], []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        db = get_db()
        pages = db.execute(
            "SELECT id, title, updated_at FROM pages WHERE status='published' "
            "AND (title LIKE ? ESCAPE '\\' OR content_md LIKE ? ESCAPE '\\') "
            "ORDER BY updated_at DESC LIMIT 50",
            (like, like),
        ).fetchall()
        questions = db.execute(
            "SELECT id, title, created_at FROM questions WHERE status!='hidden' "
            "AND (title LIKE ? ESCAPE '\\' OR content_md LIKE ? ESCAPE '\\') "
            "ORDER BY created_at DESC LIMIT 50",
            (like, like),
        ).fetchall()
    return render_template("wiki/search.html", q=q, pages=pages, questions=questions)


# ---------- 编辑权申请（页面级，批准后 24 小时有效） ----------

@bp.route("/apply-edit", methods=("GET", "POST"))
@write_required
def apply_edit():
    page_id = request.values.get("page_id", type=int)
    db = get_db()
    page = db.execute(
        "SELECT * FROM pages WHERE id=? AND status='published'", (page_id,)
    ).fetchone() if page_id else None
    if page is None:
        abort(404)
    user = current_user()
    if can_edit(page, user):
        flash("您已拥有该页面的编辑权限。", "info")
        return redirect(url_for("wiki.view", page_id=page_id))

    pending = get_pending_request(user["id"], page_id)
    grant = get_edit_grant(user["id"], page_id)
    last = db.execute(
        "SELECT * FROM edit_requests WHERE requester_id=? AND page_id=? "
        "ORDER BY id DESC LIMIT 1",
        (user["id"], page_id),
    ).fetchone()

    if request.method == "POST":
        if pending is not None:
            flash("您已有一条待审申请，请耐心等待。", "warning")
        else:
            reason = request.form.get("reason", "").strip()
            if not reason:
                flash("请填写申请理由。", "danger")
            else:
                db.execute(
                    "INSERT INTO edit_requests (requester_id, page_id, reason) VALUES (?, ?, ?)",
                    (user["id"], page_id, reason),
                )
                db.commit()
                flash("申请已提交，请等待管理员审批。", "success")
                return redirect(url_for("wiki.view", page_id=page_id))
    return render_template(
        "wiki/apply_edit.html", page=page, pending=pending, grant=grant, last=last
    )


# ---------- 举报 ----------

@bp.route("/report", methods=("GET", "POST"))
@write_required
def report():
    db = get_db()
    page_id = request.values.get("page_id", type=int)
    question_id = request.values.get("question_id", type=int)
    answer_id = request.values.get("answer_id", type=int)

    target, target_user_id = None, None
    if page_id:
        row = db.execute(
            "SELECT id, title, author_id FROM pages WHERE id=? AND status='published'",
            (page_id,),
        ).fetchone()
        if row:
            target, target_user_id = ("page", row), row["author_id"]
    elif question_id:
        row = db.execute(
            "SELECT id, title, author_id FROM questions WHERE id=? AND status!='hidden'",
            (question_id,),
        ).fetchone()
        if row:
            target, target_user_id = ("question", row), row["author_id"]
    elif answer_id:
        row = db.execute(
            "SELECT a.id, a.author_id, a.content_md, q.id AS qid, q.title FROM answers a "
            "JOIN questions q ON q.id=a.question_id "
            "WHERE a.id=? AND a.status='visible' AND q.status!='hidden'",
            (answer_id,),
        ).fetchone()
        if row:
            target, target_user_id = ("answer", row), row["author_id"]
    if target is None:
        abort(404)

    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("请填写举报理由。", "danger")
        else:
            db.execute(
                "INSERT INTO reports (reporter_id, target_user_id, page_id, question_id, answer_id, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    current_user()["id"], target_user_id,
                    page_id if target[0] == "page" else None,
                    question_id if target[0] in ("question", "answer") else (
                        target[1]["qid"] if target[0] == "answer" else None),
                    answer_id if target[0] == "answer" else None,
                    reason,
                ),
            )
            db.commit()
            flash("举报已提交，管理员会尽快处理。", "success")
            if target[0] == "page":
                return redirect(url_for("wiki.view", page_id=page_id))
            return redirect(url_for("qa.detail", question_id=question_id or target[1]["qid"]))
    return render_template("wiki/report.html", kind=target[0], row=target[1])


# ---------- 申诉（封禁异议） ----------

@bp.route("/appeal", methods=("GET", "POST"))
@login_required
def appeal():
    db = get_db()
    user = current_user()
    ban = get_active_ban(user["id"])
    appeals = db.execute(
        "SELECT a.*, b.reason AS ban_reason, b.banned_until, b.created_at AS ban_created "
        "FROM appeals a JOIN bans b ON b.id=a.ban_id "
        "WHERE a.appellant_id=? ORDER BY a.id DESC",
        (user["id"],),
    ).fetchall()
    used = pending = 0
    if ban is not None:
        used = db.execute(
            "SELECT COUNT(*) FROM appeals WHERE ban_id=?", (ban["id"],)
        ).fetchone()[0]
        pending = db.execute(
            "SELECT COUNT(*) FROM appeals WHERE ban_id=? AND status='pending'", (ban["id"],)
        ).fetchone()[0]

    if request.method == "POST":
        if ban is None:
            flash("您当前没有生效中的封禁。", "info")
            return redirect(url_for("wiki.appeal"))
        if used >= APPEAL_MAX_PER_BAN:
            flash(f"每条封禁最多可申诉 {APPEAL_MAX_PER_BAN} 次，您已用完。", "danger")
        elif pending:
            flash("您已有一条待处理的申诉，请耐心等待。", "warning")
        else:
            content = request.form.get("content", "").strip()
            if not content:
                flash("请填写申诉内容。", "danger")
            else:
                db.execute(
                    "INSERT INTO appeals (ban_id, appellant_id, content) VALUES (?, ?, ?)",
                    (ban["id"], user["id"], content),
                )
                db.commit()
                flash("申诉已提交，将由管理员审批（48 小时内未处理则由系统自动审批）。", "success")
                return redirect(url_for("wiki.appeal"))
    return render_template(
        "appeal.html", ban=ban, appeals=appeals, used=used,
        max_appeals=APPEAL_MAX_PER_BAN,
    )


# ---------- 使用规则 ----------

@bp.route("/rules")
def rules():
    return render_template("rules.html", content_html=render_md(get_setting("rules_md", "")))


# ---------- 意见箱（任何人匿名提交，不记录身份） ----------

@bp.route("/suggestion", methods=("GET", "POST"))
def suggestion():
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if not content:
            flash("请填写意见内容。", "danger")
        elif len(content) > 1000:
            flash("意见内容请控制在 1000 字以内。", "danger")
        else:
            db = get_db()
            # 匿名：仅存内容与时间，不记录任何用户信息
            db.execute("INSERT INTO suggestions (content) VALUES (?)", (content,))
            db.commit()
            flash("意见已提交，全体管理员都会看到，感谢您的反馈。", "success")
            return redirect(url_for("wiki.suggestion"))
    return render_template("suggestion.html")
