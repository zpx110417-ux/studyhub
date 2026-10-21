"""Markdown → 净化 HTML 的全站唯一渲染出口。

铁律：所有要在模板里用 |safe 输出的 HTML，必须经过本文件的 render_md()，
任何其他代码不得跳过 bleach 直接输出未净化的 HTML。
"""
import bleach
import markdown

_ALLOWED_TAGS = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "a", "img",
    "code", "pre", "blockquote", "ul", "ol", "li", "table",
    "thead", "tbody", "tr", "th", "td", "strong", "em", "del",
    "br", "hr", "sup", "sub",
]
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "th": {"align"},
    "td": {"align"},
}


def render_md(md_text):
    """渲染 Markdown 并用 bleach 白名单净化（剥离 script/iframe/onclick 等）。"""
    html = markdown.markdown(
        md_text or "",
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    )
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
