"""应用工厂：装配配置、蓝图、CSRF、安全头、模板全局变量与错误页。"""
import os

from flask import Flask, abort, redirect, render_template, request, session, url_for


def create_app():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )

    # 先加载配置，再确保 instance/（数据库、密钥）与 uploads/（上传文件）目录存在
    app.config.from_object("config")
    instance_config = os.path.join(app.instance_path, "instance_config.py")
    if os.path.exists(instance_config):
        app.config.from_pyfile(instance_config)
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    from . import db, auth, wiki, qa, uploads, admin, moderation

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(wiki.bp)
    app.register_blueprint(qa.bp)
    app.register_blueprint(uploads.bp)
    app.register_blueprint(admin.bp)
    moderation.init_app(app)  # 注册 auto-moderate CLI 命令

    @app.before_request
    def check_secret_key():
        # 防止用空密钥上线：HTTP 请求一律要求已配置 SECRET_KEY（CLI 命令不受影响）
        if not app.config.get("SECRET_KEY"):
            abort(
                500,
                "SECRET_KEY 未设置：请在 instance/instance_config.py 中写入 "
                "SECRET_KEY = \"你的密钥\"（生成方式见部署文档）。",
            )

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            sent = request.form.get("csrf_token", "")
            if not sent or sent != session.get("csrf_token"):
                abort(400, "表单校验失败（CSRF），请返回刷新页面后重试。")

    @app.before_request
    def banned_gate():
        # 封禁中的账号完全不可浏览：除封禁提示页、申诉页、退出登录外全部拦截
        if request.endpoint in ("static", "auth.banned", "auth.logout", "wiki.appeal"):
            return
        from .helpers import current_user, get_active_ban

        user = current_user()
        if user is None:
            return
        if get_active_ban(user["id"]) is not None:
            return redirect(url_for("auth.banned"))

    @app.after_request
    def set_security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    @app.teardown_appcontext
    def close_db_on_teardown(exc):
        db.close_db(exc)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(500)
    def error_page(e):
        return render_template("errors.html", code=e.code, message=e.description), e.code

    from .helpers import current_user, get_active_ban, generate_csrf

    @app.context_processor
    def inject_globals():
        user = current_user()
        ban = get_active_ban(user["id"]) if user else None
        return {"current_user": user, "active_ban": ban, "csrf_token": generate_csrf}

    return app
