from __future__ import annotations
"""文章排版模块 - 将Markdown文章转换为微信公众号兼容的HTML

输出两种HTML:
1. article.html - 完整可预览的HTML（手机预览框架，浏览器直接打开看效果）
2. article_content.html - 纯内容片段（可直接粘贴到公众号编辑器）

v3改进：
- 精美微信排版样式（参考mdnice风格）
- 图片base64内嵌（不依赖外部图床，复制即带图）
- 去掉卡兹克签名/尾部
- 去掉质检报告
"""
import base64
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


# ==================== 微信公众号精美排版CSS（多彩渐变风格） ====================

WECHAT_CSS = """
<style>
  /* 全局容器 - 微信兼容，所有元素无底色 */
  .rich_media_content {
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue",
      "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI",
      "Microsoft YaHei", Arial, sans-serif;
    font-size: 15px;
    color: #3f3f3f;
    line-height: 2.2;
    letter-spacing: 0.5px;
    padding: 0 8px;
    word-break: break-word;
    background: transparent !important;
  }

  /* 标题 - 底部彩色线，无底色 */
  h1 {
    font-size: 22px;
    font-weight: bold;
    color: #1a1a1a;
    text-align: center;
    margin: 30px 0 25px;
    padding: 8px 0 14px;
    border-bottom: 2px solid #e9d5ff;
    background: transparent !important;
  }

  h2 {
    font-size: 17px;
    font-weight: bold;
    color: #7c3aed;
    margin: 32px 0 18px;
    padding: 8px 14px;
    border-left: 4px solid #7c3aed;
    background: transparent !important;
  }

  h3 {
    font-size: 16px;
    font-weight: bold;
    color: #7c3aed;
    margin: 24px 0 12px;
    padding: 4px 0 4px 12px;
    border-left: 4px solid #ec4899;
    background: transparent !important;
  }

  /* 正文段落 - 舒适间距 */
  p {
    margin: 14px 0;
    text-align: justify;
    text-indent: 0;
    background: transparent !important;
  }

  /* 引用块 - 左边框，无底色 */
  blockquote {
    margin: 20px 0;
    padding: 16px 20px;
    border-left: 4px solid #7c3aed;
    color: #555;
    font-size: 14px;
    background: transparent !important;
  }

  blockquote p {
    margin: 6px 0;
  }

  /* 粗体 - 紫色，无底色 */
  strong {
    color: #7c3aed;
    font-weight: bold;
    background: transparent !important;
  }

  /* 斜体 */
  em {
    color: #db2777;
    font-style: italic;
  }

  /* 列表 */
  ul, ol {
    margin: 14px 0;
    padding-left: 24px;
  }

  li {
    margin: 8px 0;
    line-height: 2;
  }

  li::marker {
    color: #a855f7;
  }

  /* 分隔线 - 紫色 */
  hr {
    border: none;
    height: 1px;
    border-top: 1px solid #c4b5fd;
    margin: 32px 0;
    background: transparent !important;
  }

  /* 装饰分割线 */
  .divider-ornament {
    text-align: center;
    margin: 24px 0;
    line-height: 1;
  }
  .divider-ornament svg {
    display: inline-block;
  }

  /* 代码 - 无底色 */
  code {
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 14px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    color: #7c3aed;
    border: 1px solid #e9d5ff;
    background: transparent !important;
  }

  pre {
    border: 1px solid #ddd;
    color: #333;
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 16px 0;
    font-size: 14px;
    line-height: 1.5;
    background: transparent !important;
  }

  pre code {
    border: none;
    color: inherit;
    padding: 0;
    background: transparent !important;
  }

  /* 图片 - 圆角无阴影（微信兼容） */
  img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    margin: 20px auto;
    display: block;
  }

  /* 图片说明 */
  figcaption, .img-caption {
    text-align: center;
    font-size: 13px;
    color: #999;
    margin-top: 8px;
  }

  /* 首字下沉 - 渐变色 */
  .drop-cap::first-letter {
    font-size: 2.8em;
    float: left;
    line-height: 1;
    margin: 0 10px 0 0;
    color: #7c3aed;
    font-weight: bold;
  }

  /* 链接 */
  a {
    color: #7c3aed;
    text-decoration: none;
    border-bottom: 1px solid #c4b5fd;
  }

  /* 重点段落高亮样式 - 无底色 */
  .highlight-text {
    padding: 12px 16px;
    border-left: 3px solid #ec4899;
    margin: 16px 0;
    background: transparent !important;
  }
</style>
"""


def _image_to_base64(image_path: str) -> str:
    """将本地图片转为base64 data URI"""
    path = Path(image_path)
    if not path.exists():
        return image_path  # 文件不存在，返回原始路径

    ext = path.suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.webp': 'image/webp', '.bmp': 'image/bmp',
    }
    mime = mime_map.get(ext, 'image/jpeg')

    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode()

    return f'data:{mime};base64,{data}'


def markdown_to_wechat_html(
    markdown_text: str,
    title: str = "",
    cover_image_url: str = "",
    inline_images: list[str] = None,
    output_dir: Path = None,
) -> str:
    """
    将Markdown文本转换为微信公众号兼容的HTML片段
    （用于粘贴到公众号编辑器）

    v4: 图片base64内嵌 + 正文装饰排版（分割线、首尾装饰）
    """
    html = _md_to_html_basic(markdown_text)

    # 封面图不再插入正文（微信封面单独上传）
    # if cover_image_url:
    #     cover_src = cover_image_url
    #     if output_dir and not cover_image_url.startswith(('http', 'data:')):
    #         cover_path = output_dir / cover_image_url if not Path(cover_image_url).exists() else Path(cover_image_url)
    #         cover_src = _image_to_base64(str(cover_path))
    #     elif not cover_image_url.startswith(('http', 'data:')):
    #         cover_src = _image_to_base64(cover_image_url)
    #     cover_html = f'<img src="{cover_src}" alt="封面" style="width:100%;border-radius:8px;margin-bottom:20px;">'
    #     html = cover_html + "\n" + html

    # 插入插图（转base64）
    if inline_images and output_dir:
        base64_images = []
        for img_url in inline_images:
            if img_url.startswith(('http', 'data:')):
                base64_images.append(img_url)
            else:
                # 本地路径，转base64
                img_path = Path(img_url)
                if not img_path.exists():
                    img_path = output_dir / img_path.name
                base64_images.append(_image_to_base64(str(img_path)))
        html = _insert_inline_images(html, base64_images)
    elif inline_images:
        html = _insert_inline_images(html, inline_images)

    # 首段首字下沉
    html = _apply_drop_cap(html)

    # 去掉卡兹克签名/尾部
    html = _remove_khazix_footer(html)

    # ★ 正文装饰：在h2标题前插入装饰分割线，文章首尾加装饰
    html = _add_decorations(html)

    # ★ 注入inline style确保微信无底色（微信忽略style标签，只认inline style）
    html = _inject_no_background(html)

    # 包裹内容区
    full_html = f"""<section class="rich_media_content" style="background:none;">
{WECHAT_CSS}
{html}
</section>"""

    return full_html


def _remove_khazix_footer(html: str) -> str:
    """去掉卡兹克签名、尾部三连、投稿邮箱等标识，以及质检报告"""
    # 去掉含卡兹克关键词的段落
    patterns = [
        r'<p[^>]*>[^<]*卡兹克[^<]*</p>',
        r'<p[^>]*>[^<]*wzglyay[^<]*</p>',
        r'<p[^>]*>[^<]*virxact[^<]*</p>',
        r'<p[^>]*>[^<]*投稿或爆料[^<]*</p>',
        r'<p[^>]*>[^<]*点赞[^<]*在看[^<]*转发[^<]*</p>',
        r'<p[^>]*>[^<]*星标[^<]*</p>',
        r'<p[^>]*>[^<]*下次再见[^<]*</p>',
        r'<p[^>]*>[^<]*三连[^<]*</p>',
        r'<p[^>]*>以上[^<]*既然看到这里[^<]*</p>',
        r'<p[^>]*>谢谢你看我的文章[^<]*</p>',
        # 质检报告相关
        r'<p[^>]*>[^<]*L1[^<]*检查[^<]*</p>',
        r'<p[^>]*>[^<]*L2[^<]*检查[^<]*</p>',
        r'<p[^>]*>[^<]*四层自检[^<]*</p>',
        r'<p[^>]*>[^<]*自检报告[^<]*</p>',
        r'<p[^>]*>[^<]*质检报告[^<]*</p>',
        r'<p[^>]*>[^<]*禁用词[^<]*</p>',
        r'<p[^>]*>[^<]*禁用标点[^<]*</p>',
        r'<p[^>]*>✅[^<]*</p>',
        r'<p[^>]*>❌[^<]*</p>',
        r'<p[^>]*>⚠️[^<]*</p>',
    ]
    for pattern in patterns:
        html = re.sub(pattern, '', html, flags=re.IGNORECASE)

    # 去掉 / 作者 开头的行
    html = re.sub(r'<p[^>]*>\s*/\s*作者[^<]*</p>', '', html)

    return html


# ==================== 引导图（base64内嵌，微信兼容） ====================

# 引导图路径
_GUIDES_DIR = Path(__file__).parent.parent / "assets" / "guides"

def _get_header_guide_html() -> str:
    """获取开头引导图HTML（小黄熊+点击蓝字关注）"""
    guide_path = _GUIDES_DIR / "header_guide.jpeg"
    if not guide_path.exists():
        return _OPENING_ORNAMENT  # 降级用SVG装饰
    b64 = _image_to_base64(str(guide_path))
    return f"""<section style="text-align:center;margin:0 0 16px;">
<img src="{b64}" alt="点击蓝字关注" style="width:100%;border-radius:0;margin:0 auto;display:block;box-shadow:none;">
</section>"""

def _get_footer_guide_html() -> str:
    """获取结尾引导图HTML（点赞戳在看即刻分享）"""
    guide_path = _GUIDES_DIR / "footer_guide.jpeg"
    if not guide_path.exists():
        return _CLOSING_ORNAMENT  # 降级用SVG装饰
    b64 = _image_to_base64(str(guide_path))
    return f"""<section style="text-align:center;margin:20px 0 0;">
<img src="{b64}" alt="点赞在看分享" style="width:100%;border-radius:0;margin:0 auto;display:block;box-shadow:none;">
</section>"""


# ==================== 装饰元素（SVG内联，微信兼容） ====================

# 开头装饰：多彩花瓣/叶子
_OPENING_ORNAMENT = """<section style="text-align:center;margin:16px 0 20px;opacity:0.7;">
<svg width="140" height="20" viewBox="0 0 140 20" xmlns="http://www.w3.org/2000/svg">
  <circle cx="70" cy="10" r="3.5" fill="#7c3aed"/>
  <circle cx="58" cy="10" r="2.2" fill="#ec4899"/>
  <circle cx="82" cy="10" r="2.2" fill="#3b82f6"/>
  <line x1="25" y1="10" x2="54" y2="10" stroke="#c4b5fd" stroke-width="1"/>
  <line x1="86" y1="10" x2="115" y2="10" stroke="#c4b5fd" stroke-width="1"/>
  <circle cx="30" cy="10" r="1" fill="#c4b5fd"/>
  <circle cx="110" cy="10" r="1" fill="#c4b5fd"/>
</svg></section>"""

# 结尾装饰：多彩渐隐线条
_CLOSING_ORNAMENT = """<section style="text-align:center;margin:24px 0 16px;opacity:0.6;">
<svg width="220" height="16" viewBox="0 0 220 16" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="fadeLine" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%" stop-color="#7c3aed" stop-opacity="0"/>
    <stop offset="20%" stop-color="#7c3aed" stop-opacity="0.5"/>
    <stop offset="40%" stop-color="#ec4899" stop-opacity="0.8"/>
    <stop offset="50%" stop-color="#7c3aed" stop-opacity="1"/>
    <stop offset="60%" stop-color="#3b82f6" stop-opacity="0.8"/>
    <stop offset="80%" stop-color="#7c3aed" stop-opacity="0.5"/>
    <stop offset="100%" stop-color="#7c3aed" stop-opacity="0"/>
  </linearGradient></defs>
  <line x1="10" y1="8" x2="210" y2="8" stroke="url(#fadeLine)" stroke-width="1.5"/>
  <circle cx="110" cy="8" r="3" fill="#7c3aed"/>
  <circle cx="104" cy="8" r="1.5" fill="#ec4899"/>
  <circle cx="116" cy="8" r="1.5" fill="#3b82f6"/>
</svg></section>"""

# h2标题前分割线（三种多彩样式随机选一）
_SECTION_DIVIDERS = [
    """<section style="text-align:center;margin:20px 0 8px;opacity:0.6;">
<svg width="90" height="12" viewBox="0 0 90 12" xmlns="http://www.w3.org/2000/svg">
  <circle cx="45" cy="6" r="2.5" fill="#7c3aed"/>
  <circle cx="37" cy="6" r="1.5" fill="#ec4899"/>
  <circle cx="53" cy="6" r="1.5" fill="#3b82f6"/>
  <line x1="8" y1="6" x2="33" y2="6" stroke="#c4b5fd" stroke-width="0.8"/>
  <line x1="57" y1="6" x2="82" y2="6" stroke="#c4b5fd" stroke-width="0.8"/>
</svg></section>""",
    """<section style="text-align:center;margin:20px 0 8px;opacity:0.6;">
<svg width="70" height="12" viewBox="0 0 70 12" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 6 L28 6 M42 6 L62 6" stroke="#c4b5fd" stroke-width="0.8" fill="none"/>
  <path d="M30 6 L33 3 L36 6 L33 9 Z" fill="#ec4899"/>
  <circle cx="33" cy="6" r="1" fill="#7c3aed"/>
</svg></section>""",
    """<section style="text-align:center;margin:20px 0 8px;opacity:0.6;">
<svg width="110" height="12" viewBox="0 0 110 12" xmlns="http://www.w3.org/2000/svg">
  <line x1="12" y1="6" x2="45" y2="6" stroke="#c4b5fd" stroke-width="0.8"/>
  <circle cx="55" cy="6" r="2" fill="#ec4899"/>
  <circle cx="55" cy="6" r="4" fill="none" stroke="#7c3aed" stroke-width="0.6"/>
  <circle cx="55" cy="6" r="6" fill="none" stroke="#c4b5fd" stroke-width="0.4"/>
  <line x1="65" y1="6" x2="98" y2="6" stroke="#c4b5fd" stroke-width="0.8"/>
</svg></section>""",
]


def _add_decorations(html: str) -> str:
    """在文章中加入装饰元素：首尾引导图、标题前分割线"""
    import random

    # 1. 在文章开头加引导图（小黄熊+点击蓝字关注）
    header_guide = _get_header_guide_html()
    first_tag = re.search(r'<(p|h[1-6]|img|blockquote)', html)
    if first_tag:
        insert_pos = first_tag.start()
        html = html[:insert_pos] + header_guide + "\n" + html[insert_pos:]

    # 2. 在文章结尾加引导图（点赞戳在看即刻分享）
    footer_guide = _get_footer_guide_html()
    # 找最后一个</p>或</blockquote>或</ul>或</ol>或</section>
    last_close = max(
        html.rfind('</p>'),
        html.rfind('</blockquote>'),
        html.rfind('</ul>'),
        html.rfind('</ol>'),
        html.rfind('</section>'),
    )
    if last_close > 0:
        insert_pos = last_close + len(html[last_close:last_close+5].split('>')[0]) + 1
        html = html[:insert_pos] + "\n" + footer_guide + html[insert_pos:]

    # 3. 在每个h2标题前插入随机分割线装饰
    divider_idx = 0
    def _insert_divider(match):
        nonlocal divider_idx
        divider = _SECTION_DIVIDERS[divider_idx % len(_SECTION_DIVIDERS)]
        divider_idx += 1
        return divider + "\n" + match.group(0)

    html = re.sub(r'<h2>', _insert_divider, html)

    return html


def generate_preview_html(
    content_html: str,
    title: str = "",
    author: str = "",
    publish_date: str = "",
) -> str:
    """
    生成完整的可预览HTML文件（带手机框架预览效果）
    """
    # 从内容HTML中提取纯内容（去掉外层section包裹）
    inner_html = content_html
    if inner_html.startswith("<section"):
        match = re.search(r'<section[^>]*>(.*)</section>', inner_html, re.DOTALL)
        if match:
            inner_html = match.group(1)

    preview = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - 微信公众号文章预览</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            background: #f0f0f0;
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            padding: 20px;
        }}
        .preview-container {{
            display: flex;
            gap: 30px;
            max-width: 1200px;
            width: 100%;
        }}
        /* 手机预览框架 */
        .phone-frame {{
            width: 375px;
            min-width: 375px;
            background: #fff;
            border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            overflow: hidden;
            align-self: flex-start;
        }}
        .phone-header {{
            background: #1a1a1a;
            color: white;
            padding: 12px 16px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .phone-header .back-btn {{ font-size: 18px; cursor: pointer; }}
        .phone-header .title-bar {{
            flex: 1; text-align: center; font-size: 14px;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }}
        .phone-content {{
            padding: 0;
            min-height: 600px;
            overflow-y: auto;
        }}
        .article-meta {{
            padding: 20px 16px 12px;
            border-bottom: 1px solid #eee;
        }}
        .article-meta h1 {{
            font-size: 22px; font-weight: bold; color: #1a1a1a;
            line-height: 1.4; margin-bottom: 12px;
            text-align: left; border-bottom: none; padding-bottom: 0;
        }}
        .article-meta .meta-info {{
            display: flex; align-items: center; gap: 8px;
            font-size: 13px; color: #999;
        }}
        .article-meta .author-name {{ color: #576b95; }}
        .rich_media_content {{
            font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue",
                "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI",
                "Microsoft YaHei", Arial, sans-serif;
            font-size: 15px; color: #3f3f3f; line-height: 2.2;
            letter-spacing: 0.5px; padding: 0 16px 20px;
            background: transparent !important;
        }}
        .rich_media_content h1 {{
            font-size: 22px; font-weight: bold; color: #1a1a1a;
            text-align: center; margin: 30px 0 25px;
            padding: 8px 0 14px;
            border-bottom: 2px solid #e9d5ff;
            background: transparent !important;
        }}
        .rich_media_content h2 {{
            font-size: 17px; font-weight: bold; color: #7c3aed;
            margin: 32px 0 18px; padding: 8px 14px;
            border-left: 4px solid #7c3aed;
            background: transparent !important;
        }}
        .rich_media_content h3 {{
            font-size: 16px; font-weight: bold; color: #7c3aed;
            margin: 24px 0 12px; padding: 4px 0 4px 12px;
            border-left: 4px solid #ec4899;
            background: transparent !important;
        }}
        .rich_media_content p {{ margin: 14px 0; text-align: justify; text-indent: 0; background: transparent !important; }}
        .rich_media_content blockquote {{
            margin: 20px 0; padding: 16px 20px;
            border-left: 4px solid #7c3aed;
            color: #555; font-size: 14px;
            background: transparent !important;
        }}
        .rich_media_content blockquote p {{ margin: 6px 0; }}
        .rich_media_content strong {{
            color: #7c3aed; font-weight: bold;
            background: transparent !important;
        }}
        .rich_media_content em {{ color: #db2777; font-style: italic; }}
        .rich_media_content ul, .rich_media_content ol {{ margin: 14px 0; padding-left: 24px; }}
        .rich_media_content li {{ margin: 8px 0; line-height: 2; }}
        .rich_media_content li::marker {{ color: #a855f7; }}
        .rich_media_content hr {{
            border: none; height: 1px;
            border-top: 1px solid #c4b5fd;
            margin: 32px 0;
            background: transparent !important;
        }}
        .rich_media_content code {{
            padding: 2px 6px; border-radius: 3px;
            font-size: 14px; color: #7c3aed;
            border: 1px solid #e9d5ff;
            background: transparent !important;
        }}
        .rich_media_content pre {{
            border: 1px solid #ddd; color: #333; padding: 16px;
            border-radius: 8px; overflow-x: auto; margin: 16px 0;
            font-size: 14px; line-height: 1.5;
            background: transparent !important;
        }}
        .rich_media_content pre code {{ border: none; color: inherit; padding: 0; background: transparent !important; }}
        .rich_media_content img {{
            max-width: 100%; height: auto; border-radius: 8px;
            margin: 20px auto; display: block;
        }}
        .rich_media_content .drop-cap::first-letter {{
            font-size: 2.8em; float: left; line-height: 1;
            margin: 0 10px 0 0; color: #7c3aed; font-weight: bold;
        }}
        .rich_media_content a {{
            color: #7c3aed; text-decoration: none;
            border-bottom: 1px solid #c4b5fd;
        }}
        /* 操作提示区 */
        .tips-panel {{
            flex: 1; background: #fff; border-radius: 12px;
            padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            align-self: flex-start; max-width: 500px;
        }}
        .tips-panel h2 {{
            font-size: 18px; color: #1a1a1a; margin-bottom: 16px;
            padding-left: 0; border-left: none;
        }}
        .tips-panel .tip-item {{
            margin-bottom: 16px; padding: 12px 16px;
            background: #f8f9fa; border-radius: 8px;
        }}
        .tips-panel .tip-item .tip-title {{
            font-weight: bold; color: #7c3aed; margin-bottom: 6px; font-size: 14px;
        }}
        .tips-panel .tip-item .tip-desc {{
            font-size: 13px; color: #666; line-height: 1.6;
        }}
        .copy-btn {{
            display: inline-block; background: #7c3aed; color: white;
            border: none; padding: 10px 20px; border-radius: 8px;
            font-size: 14px; cursor: pointer; margin-top: 12px;
        }}
        .copy-btn:hover {{ background: #6d28d9; }}
        @media (max-width: 768px) {{
            .preview-container {{ flex-direction: column; align-items: center; }}
            .tips-panel {{ max-width: 375px; width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="preview-container">
        <div class="phone-frame">
            <div class="phone-header">
                <span class="back-btn">&lt;</span>
                <span class="title-bar">精选好文</span>
                <span style="width:18px"></span>
            </div>
            <div class="phone-content">
                <div class="article-meta">
                    <h1>{title or '文章标题'}</h1>
                    <div class="meta-info">
                        <span class="author-name">{author or '公众号名称'}</span>
                        <span>{publish_date or '刚刚'}</span>
                    </div>
                </div>
                <div class="rich_media_content" id="article-content">
                    {inner_html}
                </div>
            </div>
        </div>
        <div class="tips-panel">
            <h2>如何使用这篇文章</h2>
            <div class="tip-item">
                <div class="tip-title">方式一：直接复制到公众号编辑器</div>
                <div class="tip-desc">
                    点击下方按钮复制文章内容，然后在微信公众号编辑器中直接 Ctrl+V 粘贴即可。<br>
                    图片已内嵌，粘贴后图片会自动上传到微信服务器。
                </div>
                <button class="copy-btn" onclick="copyContent()">复制文章内容</button>
            </div>
            <div class="tip-item">
                <div class="tip-title">方式二：使用 Web 控制台</div>
                <div class="tip-desc">
                    在 Web 控制台点击「HTML」按钮，内容已包含排版和图片，直接粘贴到公众号编辑器。
                </div>
            </div>
        </div>
    </div>
    <script>
        function copyContent() {{
            var content = document.getElementById('article-content');
            var range = document.createRange();
            range.selectNodeContents(content);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            try {{
                document.execCommand('copy');
                var btn = document.querySelector('.copy-btn');
                btn.textContent = '已复制!';
                btn.style.background = '#22c55e';
                setTimeout(function() {{
                    btn.textContent = '复制文章内容';
                    btn.style.background = '#7c3aed';
                }}, 2000);
            }} catch(e) {{
                alert('复制失败，请手动选中内容后复制');
            }}
            selection.removeAllRanges();
        }}
    </script>
</body>
</html>"""
    return preview


def _md_to_html_basic(md: str) -> str:
    """将Markdown转为基本HTML（不依赖外部库）"""
    # 先去掉质检报告部分（## 四层自检 / ## 质检报告 及其后面的所有内容）
    cutoff = re.search(r'\n##\s*(?:四层自检|质检报告|自检报告|L[1-4]检查)', md)
    if cutoff:
        md = md[:cutoff.start()]
    # 去掉单独一行的自检标记（✅ ❌ ⚠️ 开头的行）
    md = re.sub(r'^[✅❌⚠️💡🔥⭐🚀💰📈📉].*$', '', md, flags=re.MULTILINE)

    lines = md.split("\n")
    html_parts = []
    in_code_block = False
    in_list = False
    list_type = None

    for line in lines:
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_code_block:
                html_parts.append("</code></pre>")
                in_code_block = False
            else:
                lang = stripped[3:].strip()
                html_parts.append(f'<pre><code class="language-{lang}">')
                in_code_block = True
            continue

        if in_code_block:
            html_parts.append(_escape_html(line))
            continue

        # 空行
        if not stripped:
            if in_list:
                if list_type == "ul":
                    html_parts.append("</ul>")
                else:
                    html_parts.append("</ol>")
                in_list = False
            continue

        # 标题
        if stripped.startswith("# "):
            html_parts.append(f"<h1>{_inline_format(stripped[2:])}</h1>")
            continue
        if stripped.startswith("## "):
            html_parts.append(f"<h2>{_inline_format(stripped[3:])}</h2>")
            continue
        if stripped.startswith("### "):
            html_parts.append(f"<h3>{_inline_format(stripped[4:])}</h3>")
            continue

        # 分隔线
        if stripped in ("---", "***", "___"):
            html_parts.append("<hr>")
            continue

        # 引用
        if stripped.startswith("> "):
            quote_text = _inline_format(stripped[2:])
            html_parts.append(f"<blockquote><p>{quote_text}</p></blockquote>")
            continue

        # 无序列表
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list or list_type != "ul":
                if in_list:
                    html_parts.append("</ol>" if list_type == "ol" else "</ul>")
                html_parts.append("<ul>")
                in_list = True
                list_type = "ul"
            html_parts.append(f"<li>{_inline_format(stripped[2:])}</li>")
            continue

        # 有序列表
        match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if match:
            if not in_list or list_type != "ol":
                if in_list:
                    html_parts.append("</ul>" if list_type == "ul" else "</ol>")
                html_parts.append("<ol>")
                in_list = True
                list_type = "ol"
            html_parts.append(f"<li>{_inline_format(match.group(2))}</li>")
            continue

        # 关闭列表
        if in_list:
            html_parts.append("</ul>" if list_type == "ul" else "</ol>")
            in_list = False

        # 普通段落
        html_parts.append(f"<p>{_inline_format(stripped)}</p>")

    # 关闭未闭合的列表
    if in_list:
        html_parts.append("</ul>" if list_type == "ul" else "</ol>")

    return "\n".join(html_parts)


def _inline_format(text: str) -> str:
    """处理行内格式：粗体、斜体、代码、链接"""
    text = re.sub(r"!\[(.+?)\]\((.+?)\)", r'<img src="\2" alt="\1">', text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    return text


def _escape_html(text: str) -> str:
    """转义HTML特殊字符"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _apply_drop_cap(html: str) -> str:
    """为第一个段落添加首字下沉效果"""
    match = re.search(r"<p>(.+?)</p>", html)
    if match:
        first_p = match.group(1)
        if len(first_p) > 2 and not first_p.startswith("<"):
            first_char = first_p[0]
            rest = first_p[1:]
            new_p = f'<p class="drop-cap" style="background:none;">{first_char}{rest}</p>'
            html = html.replace(f"<p>{first_p}</p>", new_p, 1)
    return html


def _inject_no_background(html: str) -> str:
    """给所有文字元素注入 inline style='background:none;'
    微信编辑器忽略<style>标签，只认inline style，所以必须逐元素注入
    """
    # 需要注入background:none的标签
    tags_to_inject = ['p', 'h1', 'h2', 'h3', 'blockquote', 'strong', 'em',
                      'code', 'pre', 'ul', 'ol', 'li', 'a', 'span', 'section']

    for tag in tags_to_inject:
        # 匹配开标签（可能已有style属性，也可能没有）
        # 情况1: <tag ...> 无style → 加 style="background:none;"
        html = re.sub(
            rf'(<{tag}\b(?![^>]*style=)[^>]*)(>)',
            rf'\1 style="background:none;"\2',
            html
        )
        # 情况2: <tag ... style="..." ...> 有style → 在style值最前面加 background:none;
        html = re.sub(
            rf'(<{tag}\b[^>]*style=")([^"]*)("[^>]*>)',
            lambda m: m.group(1) + _prepend_bg_none(m.group(2)) + m.group(3),
            html
        )

    return html


def _prepend_bg_none(style_val: str) -> str:
    """在style属性值最前面加background:none;（如果还没有的话）"""
    if 'background' in style_val.lower():
        # 已有background，替换为none
        style_val = re.sub(r'background[^;]*;?', '', style_val, flags=re.IGNORECASE)
    return f'background:none;{style_val}'


def _insert_inline_images(html: str, images: list[str]) -> str:
    """在文章正文中插入插图，默认两张图把正文分成三段。"""
    if not images:
        return html

    plain_text = re.sub(r"<[^>]+>", "", html)
    total_chars = len(plain_text)

    edge_gap = 120
    min_gap = 180
    if total_chars < edge_gap * 2 + min_gap:
        images = images[:1]
        if not images:
            return html

    parts = re.split(r"(<[^>]+>)", html)
    p_positions = []
    char_count = 0
    for i, part in enumerate(parts):
        if not part.startswith("<"):
            char_count += len(part)
        elif part == "</p>":
            p_positions.append((i, char_count))

    if not p_positions:
        return html

    usable_start = edge_gap
    usable_end = total_chars - edge_gap
    if usable_end <= usable_start:
        return html

    n_images = len(images)
    target_positions = [total_chars * (j + 1) / (n_images + 1) for j in range(n_images)]
    target_positions = [min(max(pos, usable_start), usable_end) for pos in target_positions]

    insert_points = []
    used_indices = set()
    for target in target_positions:
        best = None
        best_diff = float("inf")
        for idx, (pos, char_pos) in enumerate(p_positions):
            if idx in used_indices:
                continue
            if char_pos < usable_start or char_pos > usable_end:
                continue
            if insert_points and char_pos - insert_points[-1][1] < min_gap:
                continue
            diff = abs(char_pos - target)
            if diff < best_diff:
                best = idx
                best_diff = diff
        if best is not None:
            used_indices.add(best)
            insert_points.append(p_positions[best])

    for j in range(len(insert_points) - 1, -1, -1):
        pos_idx, char_pos = insert_points[j]
        if j < len(images):
            img_url = images[j]
            img_html = f'\n<img src="{img_url}" alt="插图" style="width:100%;border-radius:8px;margin:12px auto;">\n'
            parts.insert(pos_idx + 1, img_html)

    return "".join(parts)


def save_article_files(
    article: dict,
    html_content: str,
    output_dir: Path,
    cover_path: Optional[Path] = None,
) -> dict:
    """
    保存文章的所有文件到输出目录

    v3: meta.json不再包含质检报告
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存完整可预览HTML（带手机框架预览）
    preview_html = generate_preview_html(
        html_content,
        title=article["title"],
        author="",
        publish_date=datetime.now().strftime("%Y-%m-%d"),
    )
    preview_path = output_dir / "article.html"
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(preview_html)

    # 保存纯内容片段HTML（可直接粘贴到公众号编辑器）
    content_path = output_dir / "article_content.html"
    with open(content_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 保存Markdown原文
    md_path = output_dir / "article.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(article["raw_markdown"])

    # 保存纯文本
    txt_path = output_dir / "article.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(article["content"])

    # 保存元信息（v3: 去掉质检报告）
    meta_path = output_dir / "meta.json"
    import json
    meta = {
        "title": article["title"],
        "summary": article.get("summary", ""),
        "word_count": len(article["content"]),
        "cover_image": str(cover_path) if cover_path else None,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "html": preview_path,
        "content_html": content_path,
        "md": md_path,
        "txt": txt_path,
        "meta": meta_path,
        "cover": cover_path,
    }


if __name__ == "__main__":
    test_md = """# 测试文章

这是第一段内容，用于测试排版效果。

## 第一节

这是第一节的内容，包含了**粗体**和*斜体*。

> 这是一段引用文字

## 第二节

- 列表项1
- 列表项2
- 列表项3

---

结束。
"""
    content_html = markdown_to_wechat_html(test_md, "测试标题")
    preview_html = generate_preview_html(content_html, title="测试文章标题")

    output = Path("test_output")
    output.mkdir(exist_ok=True)
    with open(output / "preview.html", "w", encoding="utf-8") as f:
        f.write(preview_html)
    print(f"预览文件已保存到: {output / 'preview.html'}")
