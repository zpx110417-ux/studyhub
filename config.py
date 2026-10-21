"""站点配置：均有默认值，生产环境通过 instance/instance_config.py 覆盖。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 会话签名密钥：生产环境必须设置！
# 生成方式：python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.environ.get("STUDYHUB_SECRET_KEY", "")

# 上传限制
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_FILE_EXTS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "zip", "txt", "md", "mp3", "mp4",
}

# 业务规则
ADMIN_MAX_COUNT = 5             # 管理员上限
EDIT_GRANT_HOURS = 24           # 页面编辑授权有效期（小时）
PAGE_REVIEW_TIMEOUT_HOURS = 24  # 页面审批超时（超时后由系统代管）
APPEAL_TIMEOUT_HOURS = 48       # 申诉审批超时（超时后由系统代管）
APPEAL_MAX_PER_BAN = 5          # 每条封禁最多可申诉次数
BAN_DAY_CHOICES = [1, 3, 7, 14, 30]  # 封禁时长（天）
