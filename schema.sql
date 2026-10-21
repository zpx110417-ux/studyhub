-- StudyHub 数据库结构（16 张表）
-- 约定：时间统一存 SQLite datetime('now','localtime') 输出的 TEXT 格式 YYYY-MM-DD HH:MM:SS
--       日期（如 last_reject_date / last_scan_date）存 date('now','localtime') 的 YYYY-MM-DD

DROP TABLE IF EXISTS post_likes;
DROP TABLE IF EXISTS post_comments;
DROP TABLE IF EXISTS posts;
DROP TABLE IF EXISTS deletions;
DROP TABLE IF EXISTS appeals;
DROP TABLE IF EXISTS bans;
DROP TABLE IF EXISTS suggestions;
DROP TABLE IF EXISTS reports;
DROP TABLE IF EXISTS answers;
DROP TABLE IF EXISTS questions;
DROP TABLE IF EXISTS files;
DROP TABLE IF EXISTS edit_requests;
DROP TABLE IF EXISTS page_versions;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS site_settings;

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',   -- user | admin
    signature      TEXT NOT NULL DEFAULT '',       -- 个性签名（≤50 字，账户页自填）
    last_active_at TEXT,                            -- 最后活跃时间（10 分钟内算在线）
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 学习库页面（审批制发布）
CREATE TABLE pages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    content_md       TEXT NOT NULL,               -- 最新 Markdown 原文（唯一事实来源）
    content_html     TEXT NOT NULL DEFAULT '',    -- 渲染并净化后的 HTML 缓存
    author_id        INTEGER NOT NULL REFERENCES users(id),
    status           TEXT NOT NULL DEFAULT 'pending', -- pending | published | rejected | hidden
    reject_count     INTEGER NOT NULL DEFAULT 0,  -- 连续驳回计数（跨天提交时重置）
    last_reject_date TEXT NOT NULL DEFAULT '',    -- 最近一次被驳回的日期 YYYY-MM-DD
    review_note      TEXT NOT NULL DEFAULT '',    -- 最近一次驳回理由 / 系统审批说明
    reviewed_by      INTEGER REFERENCES users(id),-- NULL = 系统代管审批
    reviewed_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_pages_status ON pages(status, updated_at DESC);
CREATE INDEX idx_pages_author ON pages(author_id);

-- 页面版本（每次保存追加一行；回滚 = 旧版本内容作为新版本写入）
CREATE TABLE page_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id    INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    editor_id  INTEGER NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL,
    content_md TEXT NOT NULL,
    comment    TEXT NOT NULL DEFAULT '',
    edited_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_versions_page ON page_versions(page_id, edited_at DESC);

-- 页面编辑权申请（页面级授权，批准后 24 小时内有效）
CREATE TABLE edit_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES users(id),
    page_id      INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    reason       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected | revoked
    reviewed_by  INTEGER REFERENCES users(id),
    expires_at   TEXT,                            -- 仅 approved 有值：批准时间 + 24h
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
-- 一人对同一页面同时只能有一条待审申请
CREATE UNIQUE INDEX idx_requests_pending
    ON edit_requests(requester_id, page_id) WHERE status = 'pending';

-- 问答帖（免审批直接发布）
CREATE TABLE questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id    INTEGER NOT NULL REFERENCES users(id),
    title        TEXT NOT NULL,
    content_md   TEXT NOT NULL,
    content_html TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'open',    -- open | closed | hidden
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    author_id    INTEGER NOT NULL REFERENCES users(id),
    content_md   TEXT NOT NULL,
    content_html TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'visible', -- visible | hidden
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_answers_question ON answers(question_id);

-- 上传文件记录（存储名用 uuid 重命名，原始文件名在下载时恢复展示）
CREATE TABLE files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uploader_id INTEGER NOT NULL REFERENCES users(id),
    orig_name   TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    ext         TEXT NOT NULL,
    size        INTEGER NOT NULL,
    is_image    INTEGER NOT NULL DEFAULT 0,     -- 1 = 图片（内联展示），0 = 附件（下载）
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 报刊（朋友圈式：实名/匿名发帖，文字+图片，可点赞与评论）
CREATE TABLE posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id    INTEGER NOT NULL REFERENCES users(id),
    anonymous    INTEGER NOT NULL DEFAULT 0,     -- 1 = 对外匿名展示（管理员后台仍可见真实作者）
    content_md   TEXT NOT NULL,
    content_html TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'visible', -- visible | hidden
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_posts_time ON posts(created_at DESC);

-- 报刊点赞（一人一帖最多一赞，再点取消）
CREATE TABLE post_likes (
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (post_id, user_id)
);

-- 报刊评论
CREATE TABLE post_comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_id    INTEGER NOT NULL REFERENCES users(id),
    content_md   TEXT NOT NULL,
    content_html TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'visible', -- visible | hidden
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_comments_post ON post_comments(post_id);

-- 举报（reporter_id 为 NULL 表示系统识别）
CREATE TABLE reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id     INTEGER REFERENCES users(id),
    target_user_id  INTEGER NOT NULL REFERENCES users(id),
    page_id         INTEGER REFERENCES pages(id) ON DELETE SET NULL,
    question_id     INTEGER REFERENCES questions(id) ON DELETE SET NULL,
    answer_id       INTEGER REFERENCES answers(id) ON DELETE SET NULL,
    post_id         INTEGER REFERENCES posts(id) ON DELETE SET NULL,
    post_comment_id INTEGER REFERENCES post_comments(id) ON DELETE SET NULL,
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | dismissed | actioned
    handled_by      INTEGER REFERENCES users(id),
    handled_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_reports_status ON reports(status, created_at DESC);

-- 封禁（小黑屋）：封禁期间账号完全不可浏览，仅可查看封禁提示页并申诉
CREATE TABLE bans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    reason       TEXT NOT NULL,
    evidence     TEXT NOT NULL DEFAULT '',        -- 导致封禁的不当言论快照（封禁时从被举报内容截取）
    banned_by    INTEGER NOT NULL REFERENCES users(id),
    banned_until TEXT NOT NULL,
    lifted_at    TEXT,                            -- 提前解封时间，NULL = 未解封
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_bans_user ON bans(user_id);

-- 封禁申诉（每条封禁最多 5 次，5 次审批中包含执行封禁的管理员；每位管理员限审 1 次；NULL = 系统代管）
CREATE TABLE appeals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ban_id       INTEGER NOT NULL REFERENCES bans(id) ON DELETE CASCADE,
    appellant_id INTEGER NOT NULL REFERENCES users(id),
    content      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
    reviewed_by  INTEGER REFERENCES users(id),
    reviewed_at  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_appeals_ban ON appeals(ban_id);

-- 删除公示：管理员删帖必须给出理由，文章名/理由/删除者公开展示（原帖物理删除，此处存快照）
CREATE TABLE deletions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,                  -- page | question
    title       TEXT NOT NULL,                  -- 被删文章名快照
    reason      TEXT NOT NULL,
    admin_id    INTEGER NOT NULL REFERENCES users(id),
    admin_name  TEXT NOT NULL,                  -- 删除者用户名快照
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_deletions_time ON deletions(created_at DESC);

-- 站点设置（使用规则、敏感词词库等）
CREATE TABLE site_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

-- 意见箱（任何人匿名提交，不记录提交者身份；全部管理员后台共见）
CREATE TABLE suggestions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT NOT NULL,
    handled    INTEGER NOT NULL DEFAULT 0,      -- 0 = 未处理，1 = 已处理
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

INSERT OR IGNORE INTO site_settings (key, value) VALUES ('last_scan_date', '');
