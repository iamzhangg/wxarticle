"""参考文章解析模块 - 支持 HTML/WORD/PDF/MD/TXT/MHTML 格式"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional


def parse_html(filepath: Path) -> str:
    """解析HTML文件，提取正文文本，特别支持内容平台文章"""
    from bs4 import BeautifulSoup
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    # 移除脚本和样式
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    # 按优先级查找正文容器
    # 1. 内容平台文章：id="js_content" 是纯正文区域
    article = soup.find("div", id="js_content")
    if article:
        return article.get_text(separator="\n", strip=True)
    # 2. 内容平台文章：id="img-content" 包含标题+正文
    article = soup.find("div", id="img-content")
    if article:
        return article.get_text(separator="\n", strip=True)
    # 3. 通用：article 标签
    article = soup.find("article")
    if article:
        return article.get_text(separator="\n", strip=True)
    # 4. 通用：class 含 content 的 div
    article = soup.find("div", class_=lambda c: c and "content" in str(c).lower())
    if article:
        return article.get_text(separator="\n", strip=True)
    # 5. 兜底：取 body 全文（移除已清理的标签后）
    body = soup.find("body")
    if body:
        return body.get_text(separator="\n", strip=True)
    return soup.get_text(separator="\n", strip=True)


def parse_mhtml(filepath: Path) -> str:
    """解析MHTML文件，提取HTML部分并解析"""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    # 找到HTML内容部分
    parts = content.split("Content-Type: text/html")
    if len(parts) > 1:
        html_part = parts[1]
        # 找到下一个boundary或结束
        boundary_marker = "--"
        idx = html_part.find(boundary_marker, 10)
        if idx > 0:
            html_part = html_part[:idx]
        # 移除Content-Transfer-Encoding头部
        blank_idx = html_part.find("\n\n")
        if blank_idx > 0:
            html_content = html_part[blank_idx:]
        else:
            html_content = html_part
        # 临时保存为HTML再解析
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    return ""


def parse_docx(filepath: Path) -> str:
    """解析Word文档"""
    from docx import Document
    doc = Document(str(filepath))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def parse_pdf(filepath: Path) -> str:
    """解析PDF文件 - 使用简单文本提取"""
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pdfminer.tools.pdf2txt", str(filepath)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    # 备用：用PyMuPDF
    try:
        import fitz
        doc = fitz.open(str(filepath))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text.strip()
    except ImportError:
        return "[PDF解析失败：请安装 pdfminer.six 或 PyMuPDF]"


def parse_markdown(filepath: Path) -> str:
    """解析Markdown文件"""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


def parse_txt(filepath: Path) -> str:
    """解析纯文本文件"""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


# 格式 -> 解析函数映射
PARSERS = {
    ".html": parse_html,
    ".htm": parse_html,
    ".mhtml": parse_mhtml,
    ".mht": parse_mhtml,
    ".docx": parse_docx,
    ".doc": parse_docx,
    ".pdf": parse_pdf,
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".txt": parse_txt,
}


def parse_article(filepath: Path) -> Optional[dict]:
    """
    解析单篇文章，返回 {title, content, filepath} 或 None
    """
    ext = filepath.suffix.lower()
    parser = PARSERS.get(ext)
    if not parser:
        print(f"  ⚠ 不支持的格式: {filepath.name}")
        return None
    try:
        content = parser(filepath)
        if not content or len(content.strip()) < 50:
            print(f"  ⚠ 文章内容过短或为空: {filepath.name}")
            return None
        title = filepath.stem
        # 尝试从内容中提取标题（取第一行非空短文本）
        first_line = content.split("\n")[0].strip()
        if 5 < len(first_line) < 80:
            title = first_line
        return {
            "title": title,
            "content": content,
            "filepath": str(filepath),
        }
    except Exception as e:
        print(f"  ✗ 解析失败 {filepath.name}: {e}")
        return None


def load_reference_articles(input_dir: Path, max_count: int = 5) -> list[dict]:
    """
    从 input_dir 加载参考文章，按修改时间倒序排列，最多 max_count 篇
    """
    if not input_dir.exists():
        print(f"  ⚠ 输入目录不存在: {input_dir}")
        return []

    supported_exts = set(PARSERS.keys())
    files = []
    for f in input_dir.iterdir():
        if f.is_file() and f.suffix.lower() in supported_exts:
            files.append(f)

    if not files:
        print(f"  ⚠ 输入目录中没有找到支持格式的文章: {input_dir}")
        return []

    # 按修改时间倒序
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    files = files[:max_count]

    articles = []
    for f in files:
        print(f"  [REF] 解析: {f.name}")
        result = parse_article(f)
        if result:
            articles.append(result)

    print(f"  [OK] 成功加载 {len(articles)} 篇参考文章")
    return articles


if __name__ == "__main__":
    import sys
    from config import INPUT_DIR
    arts = load_reference_articles(INPUT_DIR)
    for a in arts:
        print(f"\n--- {a['title']} ---")
        print(a['content'][:300])
