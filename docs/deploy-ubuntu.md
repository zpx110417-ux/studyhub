# StudyHub 部署指南（Ubuntu 服务器）

面向编程新手的完整部署步骤，从零开始把学习库网站跑起来。
每一步都可以直接复制粘贴执行。全程大约 15~30 分钟。

---

## 0. 你需要准备什么

| 项目 | 说明 |
|------|------|
| Ubuntu 服务器 | 20.04 / 22.04 / 24.04 均可，1 核 1G 内存就够 |
| 服务器 IP | 例如 `123.45.67.89` |
| SSH 登录方式 | 例如 `ssh root@123.45.67.89`（云厂商控制台可查） |
| 域名（可选） | 没有域名也能用 `http://服务器IP` 访问 |

> 以下命令如无特别说明，都在**服务器**上执行。
> 本地电脑上传文件的命令会在对应步骤标注。

---

## 1. 安装系统依赖（服务器上执行）

```bash
apt update
apt install -y python3 python3-venv python3-pip nginx sqlite3
```

- `python3`：运行网站程序
- `nginx`：把 80 端口的请求转交给网站程序（也负责静态文件）
- `sqlite3`：数据库（网站数据就是一个文件，无需安装数据库服务）

---

## 2. 创建专用运行账号（不要用 root 跑网站）

```bash
adduser --disabled-password --gecos "" studyhub
```

---

## 3. 上传代码到服务器

**重要：** 请把代码放在**纯英文路径**下，推荐 `/opt/studyhub`。

在**本地电脑**（`studyhub` 项目文件夹的上一层目录）执行：

```bash
# Windows 用户请用 WinSCP 图形界面拖拽上传到 /opt/studyhub
scp -r studyhub root@123.45.67.89:/opt/studyhub
```

回到**服务器**，把目录所有权交给专用账号：

```bash
chown -R studyhub:studyhub /opt/studyhub
```

> 注意：本地的 `venv/`、`instance/`、`uploads/`、`__pycache__/` 不需要上传
> （.gitignore 里列出的都是运行时生成的）。

---

## 4. 安装 Python 依赖

```bash
cd /opt/studyhub
sudo -u studyhub python3 -m venv venv
sudo -u studyhub ./venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

国内服务器用 `-i` 指定清华镜像，速度快很多。共 5 个依赖：flask、gunicorn、markdown、bleach、pillow。

---

## 5. 生成站点配置（密钥等）

```bash
sudo -u studyhub mkdir -p /opt/studyhub/instance
KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sudo -u studyhub tee /opt/studyhub/instance/instance_config.py > /dev/null <<EOF
SECRET_KEY = "$KEY"
EOF
chmod 600 /opt/studyhub/instance/instance_config.py
```

`SECRET_KEY` 用于登录会话签名，**每台服务器只生成一次，泄露后必须更换**。

---

## 6. 初始化数据库 + 创建第一位管理员

```bash
cd /opt/studyhub
sudo -u studyhub ./venv/bin/python -m flask --app wsgi init-db
sudo -u studyhub ./venv/bin/python -m flask --app wsgi create-admin
```

按提示输入管理员用户名和密码（密码至少 6 位）。
管理员上限 5 位，其余管理员以后由现有管理员在网页后台创建。

> 也可以非交互式指定密码（适合脚本）：`create-admin --password 你的密码`

---

## 7. 手动试跑一次（确认能起来）

```bash
sudo -u studyhub /opt/studyhub/venv/bin/gunicorn \
  --workers 2 --bind 127.0.0.1:8000 --timeout 60 wsgi:app
```

看到类似 `Listening at: http://127.0.0.1:8000` 即成功。
按 `Ctrl+C` 停止，然后继续下一步把它做成开机自启服务。

---

## 8. 注册为系统服务（开机自启、崩溃自动拉起）

```bash
tee /etc/systemd/system/studyhub.service > /dev/null <<'EOF'
[Unit]
Description=StudyHub web site (gunicorn)
After=network.target

[Service]
User=studyhub
Group=studyhub
WorkingDirectory=/opt/studyhub
ExecStart=/opt/studyhub/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 --timeout 60 wsgi:app
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now studyhub
systemctl status studyhub --no-pager
```

以后常用命令：

```bash
systemctl restart studyhub   # 重启
systemctl stop studyhub      # 停止
journalctl -u studyhub -n 50 # 看最近 50 行日志
```

---

## 9. 配置 Nginx（对外 80 端口）

```bash
tee /etc/nginx/sites-available/studyhub > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;            # 有域名就替换成你的域名，例如 wiki.school.edu.cn

    # 上传大小限制：应用层 10MB，这里放宽到 12MB 留出表单余量
    client_max_body_size 12m;

    # 静态资源（CSS/JS/前端库）直接由 Nginx 提供，带 7 天缓存
    location /static/ {
        alias /opt/studyhub/static/;
        expires 7d;
        access_log off;
    }

    # 其余全部转交给网站程序
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/studyhub /etc/nginx/sites-enabled/studyhub
rm -f /etc/nginx/sites-enabled/default     # 移除默认欢迎页
nginx -t && systemctl reload nginx
```

此时浏览器访问 `http://服务器IP` 应该就能看到学习库首页。

---

## 10. 配置"系统代管"定时任务（重要，不要漏）

系统代管功能（审批 24 小时超时代管、申诉 48 小时超时自动驳回、每日全站敏感词扫描）
由 `auto-moderate` 命令完成，需要每小时执行一次：

```bash
sudo -u studyhub mkdir -p /opt/studyhub/logs
crontab -u studyhub -e
```

在打开的文件末尾加入这一行（保存退出）：

```
0 * * * * cd /opt/studyhub && ./venv/bin/python -m flask --app wsgi auto-moderate >> logs/automoderate.log 2>&1
```

---

## 11. 防火墙（可选但推荐）

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
```

---

## 12. HTTPS（可选，有域名时推荐）

有域名且已解析到服务器后，一条命令装免费证书：

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d 你的域名
```

certbot 会自动改好 Nginx 配置并每 90 天自动续期。

---

## 13. 日常维护

### 更新网站代码

在**本地电脑**重新 `scp -r` 上传（或用 git 拉取），然后服务器上：

```bash
cd /opt/studyhub
systemctl restart studyhub
```

### 数据备份（建议配置一次，永久生效）

```bash
sudo -u studyhub mkdir -p /opt/studyhub/backup
crontab -u studyhub -e
```

加入这一行（每天凌晨 3 点备份数据库与上传文件，保留 14 天）：

```
0 3 * * * cd /opt/studyhub && sqlite3 instance/studyhub.db ".backup 'backup/db-$(date +\%F).db'" && tar czf backup/uploads-$(date +\%F).tar.gz uploads 2>/dev/null; find backup -mtime +14 -delete
```

恢复方法：停止服务 → 用某个 `db-日期.db` 覆盖 `instance/studyhub.db` → 启动服务。

---

## 14. 常见问题（FAQ）

**Q1：访问显示 502 Bad Gateway？**
网站程序没起来。`journalctl -u studyhub -n 50` 看报错。最常见原因是 `instance_config.py` 缺失或 `SECRET_KEY` 为空。

**Q2：上传图片提示失败？**
1) 检查文件是否超过 10MB；2) 检查 `uploads/` 目录权限：`chown -R studyhub:studyhub /opt/studyhub/uploads`。

**Q3：管理员密码忘了？**
```bash
sudo -u studyhub ./venv/bin/python -m flask --app wsgi create-admin   # 新建一个管理员
```
然后用新管理员在"用户管理"里重置旧账号（或先删旧账号再重建）。

**Q4：提示 "database is locked"？**
正常情况下不会出现（已开启 WAL 模式 + 5 秒等待）。若频繁出现，说明备份或扫描任务与高峰写操作撞车，把 cron 时间挪到凌晨。

**Q5：想换个端口？**
把 systemd 文件和 Nginx 配置里的 `8000` 同步改掉，然后：
```bash
systemctl daemon-reload && systemctl restart studyhub && systemctl reload nginx
```

**Q6：如何确认系统代管在正常工作？**
```bash
tail /opt/studyhub/logs/automoderate.log
```
每小时整点应有新记录（无待处理事项时输出类似"自动审批：无"）。

**Q7：管理员已经 5 位了，页面提示无法创建？**
这是设计上限。如需更换：先在后台把某位管理员降为普通用户，再创建新的。

---

## 附录：项目目录结构

```
/opt/studyhub/
├── wsgi.py            # 生产入口（gunicorn 加载它）
├── run.py             # 本地开发入口（python3 run.py）
├── requirements.txt   # Python 依赖清单
├── config.py          # 站点配置（业务参数）
├── schema.sql         # 数据库表结构
├── app/               # 网站程序（11 个 Python 模块）
├── templates/         # 页面模板
├── static/            # 样式、脚本、前端库（全部本地化，无外网依赖）
├── instance/          # 运行数据：studyhub.db 数据库 + instance_config.py 密钥
├── uploads/           # 用户上传的图片和附件
├── backup/            # 自动备份（按第 13 节配置后生成）
└── venv/              # Python 虚拟环境
```
