"""SQLite 连接管理与 CLI 命令（init-db / create-admin）。"""
import os
import re
import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from config import ADMIN_MAX_COUNT

USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fa5]{3,30}$")

# 首次建库时写入的默认使用规则（管理员之后可在后台修改）
DEFAULT_RULES = """## 学习库使用规则

欢迎来到学习库！为维护良好的学习氛围，请遵守以下规则：

1. **内容规范**：发布与学习相关的内容，不发布违法、色情、暴力、广告等不良信息。
2. **审批制度**：新建页面需经管理员审批后发布；连续被驳回 3 次的页面当天不可再次提交（次日可再试）。
3. **编辑权限**：编辑他人创建的页面需要申请授权，授权仅对该页面生效，有效期为 24 小时。
4. **禁止行为**：恶意灌水、抄袭、人身攻击、传播敏感内容。
5. **举报机制**：发现违规内容可点击"举报"，系统也会自动识别部分违规内容并提交管理员。
6. **处罚措施**：违规者将被管理员封禁（1~30 天），被封禁者可在申诉页提出异议，由另一位管理员审批。

请文明使用学习库，共同维护良好的学习环境。
"""


def get_db():
    """获取当前请求的数据库连接（请求结束自动关闭，见 app/__init__.py）。"""
    if "db" not in g:
        db_path = os.path.join(current_app.instance_path, "studyhub.db")
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """建库：执行 schema.sql 并写入默认站点配置。注意会清空现有数据。"""
    db = get_db()
    schema = os.path.join(os.path.dirname(current_app.root_path), "schema.sql")
    with open(schema, encoding="utf-8") as f:
        db.executescript(f.read())
    db.executemany(
        "INSERT OR IGNORE INTO site_settings (key, value) VALUES (?, ?)",
        [("rules_md", DEFAULT_RULES), ("words_high", ""), ("words_low", "")],
    )
    db.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """初始化数据库（会清空现有数据）。"""
    init_db()
    click.echo("数据库已初始化（instance/studyhub.db）。")


@click.command("create-admin")
@click.option("--password", default=None,
              help="非交互式指定密码（不传则在终端交互输入，适合脚本与部署使用）")
@with_appcontext
def create_admin_command(password):
    """创建管理员账号（管理员总数不超过 5 位）。"""
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    if count >= ADMIN_MAX_COUNT:
        click.echo(f"管理员数量已达上限（{ADMIN_MAX_COUNT} 位），无法继续创建。")
        return
    username = click.prompt("管理员用户名").strip()
    if not USERNAME_RE.fullmatch(username):
        click.echo("用户名需为 3~30 位字母、数字、下划线或中文。")
        return
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        click.echo("该用户名已存在。")
        return
    if password is None:
        password = click.prompt("密码（至少 6 位）", hide_input=True, confirmation_prompt=True)
    if len(password) < 6:
        click.echo("密码至少 6 位。")
        return
    db.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
        (username, generate_password_hash(password, method="pbkdf2:sha256")),
    )
    db.commit()
    click.echo(f"管理员 {username} 创建成功。")


def init_app(app):
    """注册 CLI 命令（flask init-db / flask create-admin）。"""
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_admin_command)
