"""内容安全：敏感词检测（高危实时拦截 / 中危标记举报）与 auto-moderate 系统代管命令。

管理员在后台 /admin/settings 维护两级词库（逗号或换行分隔）：
- words_high 高危词：发帖/编辑保存时实时拦截，直接拒绝发布；
- words_low  中危词：不拦截，自动生成系统举报交管理员复核；每日扫描命中则隐藏内容。
"""
import click
from flask import current_app
from flask.cli import with_appcontext

from .db import get_db
from .helpers import get_setting


def parse_words(raw):
    """把逗号/换行分隔的词库文本解析成词列表。"""
    return [w.strip() for w in (raw or "").replace("\r", "").replace("\n", ",").split(",") if w.strip()]


def get_words(level):
    """level: 'high'（高危）或 'low'（中危）。"""
    return parse_words(get_setting(f"words_{level}"))


def scan_text(text, words):
    """返回 text 命中的敏感词列表（去重排序）。"""
    return sorted({w for w in words if w and w in (text or "")})


def check_high(text):
    """高危词检查：命中返回错误提示文案（调用方中止保存），未命中返回 None。"""
    hits = scan_text(text, get_words("high"))
    if hits:
        return f"内容包含不允许发布的词语（{', '.join(hits[:5])}），请修改后再提交。"
    return None


def flag_low(text, author_id, page_id=None, question_id=None, answer_id=None,
             post_id=None, post_comment_id=None):
    """中危词检查：命中自动生成系统举报（交管理员复核），不影响内容保存。"""
    hits = scan_text(text, get_words("low"))
    if hits:
        get_db().execute(
            "INSERT INTO reports (reporter_id, target_user_id, page_id, question_id, answer_id, "
            "post_id, post_comment_id, reason) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
            (
                author_id,
                page_id,
                question_id,
                answer_id,
                post_id,
                post_comment_id,
                f"系统识别：内容包含需人工复核的词语（{', '.join(hits[:5])}）",
            ),
        )
    return hits


# ---------- 系统代管（cron 每小时执行 flask auto-moderate） ----------

def _auto_review_pages(db):
    """审批超时的待审页面：含中危词 → 系统驳回；否则 → 系统发布。"""
    low_words = get_words("low")
    hours = current_app.config["PAGE_REVIEW_TIMEOUT_HOURS"]
    rows = db.execute(
        "SELECT id, content_md FROM pages WHERE status='pending' "
        "AND updated_at < datetime('now','localtime', ?)",
        (f"-{hours} hours",),
    ).fetchall()
    published = rejected = 0
    for p in rows:
        hits = scan_text(p["content_md"], low_words)
        if hits:
            note = f"系统自动审批：提交后 {hours} 小时未处理且内容含需复核词语，已自动驳回"
            db.execute(
                "UPDATE pages SET status='rejected', reject_count=reject_count+1, "
                "last_reject_date=date('now','localtime'), review_note=?, reviewed_by=NULL, "
                "reviewed_at=datetime('now','localtime') WHERE id=?",
                (note, p["id"]),
            )
            rejected += 1
        else:
            note = f"系统自动审批：提交后 {hours} 小时无管理员处理，自动通过发布"
            db.execute(
                "UPDATE pages SET status='published', reviewed_by=NULL, "
                "reviewed_at=datetime('now','localtime'), review_note=?, reject_count=0 WHERE id=?",
                (note, p["id"]),
            )
            published += 1
    return published, rejected


def _auto_reject_appeals(db):
    """申诉超时（48h）的待审申诉：系统自动驳回，维持封禁。"""
    hours = current_app.config["APPEAL_TIMEOUT_HOURS"]
    rows = db.execute(
        "SELECT id FROM appeals WHERE status='pending' "
        "AND created_at < datetime('now','localtime', ?)",
        (f"-{hours} hours",),
    ).fetchall()
    for a in rows:
        db.execute(
            "UPDATE appeals SET status='rejected', reviewed_by=NULL, "
            "reviewed_at=datetime('now','localtime') WHERE id=?",
            (a["id"],),
        )
    return len(rows)


def _daily_scan(db):
    """每日全站扫描（每自然日只执行一次）：命中词的已发布内容自动隐藏并生成系统举报。"""
    today = db.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
    if get_setting("last_scan_date", "") == today:
        return 0
    all_words = get_words("high") + get_words("low")
    hidden = 0
    if all_words:
        # 已发布页面
        for p in db.execute(
            "SELECT id, author_id, title, content_md FROM pages WHERE status='published'"
        ).fetchall():
            hits = scan_text(p["content_md"], all_words) + scan_text(p["title"], all_words)
            if hits:
                db.execute("UPDATE pages SET status='hidden' WHERE id=?", (p["id"],))
                _insert_scan_report(db, p["author_id"], page_id=p["id"], hits=hits)
                hidden += 1
        # 问题（含已关闭的）
        for q in db.execute(
            "SELECT id, author_id, title, content_md FROM questions WHERE status IN ('open','closed')"
        ).fetchall():
            hits = scan_text(q["content_md"], all_words) + scan_text(q["title"], all_words)
            if hits:
                db.execute("UPDATE questions SET status='hidden' WHERE id=?", (q["id"],))
                _insert_scan_report(db, q["author_id"], question_id=q["id"], hits=hits)
                hidden += 1
        # 可见回答
        for a in db.execute(
            "SELECT a.id, a.author_id, a.question_id, a.content_md FROM answers a "
            "JOIN questions q ON q.id=a.question_id WHERE a.status='visible' AND q.status!='hidden'"
        ).fetchall():
            hits = scan_text(a["content_md"], all_words)
            if hits:
                db.execute("UPDATE answers SET status='hidden' WHERE id=?", (a["id"],))
                _insert_scan_report(
                    db, a["author_id"], question_id=a["question_id"], answer_id=a["id"], hits=hits
                )
                hidden += 1
    db.execute(
        "INSERT INTO site_settings (key, value) VALUES ('last_scan_date', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (today,),
    )
    return hidden


def _insert_scan_report(db, author_id, page_id=None, question_id=None, answer_id=None, hits=()):
    db.execute(
        "INSERT INTO reports (reporter_id, target_user_id, page_id, question_id, answer_id, reason) "
        "VALUES (NULL, ?, ?, ?, ?, ?)",
        (
            author_id,
            page_id,
            question_id,
            answer_id,
            f"系统识别：每日扫描发现敏感词（{', '.join(sorted(set(hits))[:5])}），已自动隐藏，请管理员复核",
        ),
    )


@click.command("auto-moderate")
@with_appcontext
def auto_moderate_command():
    """系统代管：审批超时判定 / 申诉超时判定 / 每日全站扫描（供 cron 每小时调用）。"""
    db = get_db()
    published, rejected = _auto_review_pages(db)
    appeals = _auto_reject_appeals(db)
    hidden = _daily_scan(db)
    db.commit()
    click.echo(
        f"[auto-moderate] 自动发布 {published} 篇；自动驳回 {rejected} 篇；"
        f"系统驳回申诉 {appeals} 条；每日扫描隐藏 {hidden} 条内容。"
    )


def init_app(app):
    app.cli.add_command(auto_moderate_command)
