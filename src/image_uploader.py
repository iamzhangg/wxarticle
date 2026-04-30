from __future__ import annotations
"""
图片上传模块 - 将图片上传到SM.MS图床，获取在线URL

SM.MS图床：
- 免费5GB存储
- 支持PNG/JPG/GIF/BMP/WEBP
- 单文件最大5MB
- 无需注册即可使用（有API更稳定）
- API文档: https://sm.ms/doc/
"""
import os
from pathlib import Path
from typing import Optional

import requests

# SM.MS API地址
SMMS_API = "https://sm.ms/api/v2"

# 可选：SM.MS API Token（注册后获取，更稳定）
SMMS_TOKEN = os.getenv("SMMS_TOKEN", "")


def upload_image(image_path: str | Path, retries: int = 3) -> Optional[str]:
    """
    上传图片到SM.MS图床
    返回在线URL，失败返回None

    Args:
        image_path: 本地图片路径
        retries: 重试次数
    """
    image_path = Path(image_path)
    if not image_path.exists():
        print(f"  [ERROR] 图片不存在: {image_path}")
        return None

    # 检查文件大小（5MB限制）
    file_size = image_path.stat().st_size
    if file_size > 5 * 1024 * 1024:
        print(f"  [WARN] 图片太大({file_size / 1024 / 1024:.1f}MB)，跳过上传")
        return None

    headers = {}
    if SMMS_TOKEN:
        headers["Authorization"] = f"Bearer {SMMS_TOKEN}"

    for attempt in range(1, retries + 1):
        try:
            with open(image_path, "rb") as f:
                files = {"smfile": (image_path.name, f, _get_content_type(image_path))}
                data = {}

                resp = requests.post(
                    f"{SMMS_API}/upload",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60,
                )

            if resp.status_code != 200:
                print(f"  [WARN] 上传失败 HTTP {resp.status_code} (attempt {attempt}/{retries})")
                continue

            result = resp.json()

            # 上传成功
            if result.get("success") or result.get("code") == "success":
                url = result.get("data", {}).get("url", "")
                if url:
                    print(f"  [OK] 图片已上传: {image_path.name} → {url}")
                    return url

            # 图片已存在（SM.MS会返回已有URL）
            if result.get("code") == "image_repeated":
                url = result.get("images", "")
                if not url:
                    # 从data中获取
                    url = result.get("data", {}).get("url", "")
                if url:
                    print(f"  [OK] 图片已存在: {image_path.name} → {url}")
                    return url

            # 其他错误
            msg = result.get("message", "unknown error")
            print(f"  [WARN] 上传失败: {msg} (attempt {attempt}/{retries})")

            # 如果是频率限制，等待更久
            if "rate" in msg.lower() or "limit" in msg.lower():
                import time
                time.sleep(5)

        except Exception as e:
            print(f"  [WARN] 上传异常: {e} (attempt {attempt}/{retries})")

    print(f"  ✗ 图片上传最终失败: {image_path.name}")
    return None


def upload_all_images(image_dir: str | Path) -> dict[str, str]:
    """
    上传目录下所有图片到SM.MS图床
    返回 {文件名: 在线URL} 的映射

    Args:
        image_dir: 包含图片的目录路径
    """
    image_dir = Path(image_dir)
    if not image_dir.exists():
        print(f"  [WARN] 目录不存在: {image_dir}")
        return {}

    # 支持的图片格式
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    url_map = {}
    for f in sorted(image_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in image_exts:
            url = upload_image(f)
            if url:
                url_map[f.name] = url
            # 上传间隔，避免频率限制
            import time
            time.sleep(1)

    print(f"  [STAT] 上传完成: {len(url_map)}/{len([f for f in image_dir.iterdir() if f.suffix.lower() in image_exts])} 张")
    return url_map


def replace_local_urls_in_html(html_content: str, url_map: dict[str, str]) -> str:
    """
    将HTML中的本地图片路径替换为在线URL

    Args:
        html_content: HTML内容
        url_map: {本地文件名: 在线URL} 映射

    Returns:
        替换后的HTML
    """
    import re

    for filename, online_url in url_map.items():
        # 替换各种可能的本地路径格式
        # 1. 纯文件名: src="cover.jpg"
        html_content = html_content.replace(f'src="{filename}"', f'src="{online_url}"')
        # 2. 带路径: src="output/2026-04-26/情感赛道/cover.jpg"
        html_content = re.sub(
            rf'src="[^"]*[/\\]{re.escape(filename)}"',
            f'src="{online_url}"',
            html_content,
        )
        # 3. 单引号版本
        html_content = html_content.replace(f"src='{filename}'", f'src="{online_url}"')
        html_content = re.sub(
            rf"src='[^']*[/\\]{re.escape(filename)}'",
            f'src="{online_url}"',
            html_content,
        )

    return html_content


def _get_content_type(path: Path) -> str:
    """根据文件扩展名返回Content-Type"""
    ext = path.suffix.lower()
    content_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    return content_types.get(ext, "application/octet-stream")


if __name__ == "__main__":
    # 测试
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        url = upload_image(path)
        if url:
            print(f"\n在线URL: {url}")
        else:
            print("\n上传失败")
    else:
        print("用法: python image_uploader.py <图片路径>")
