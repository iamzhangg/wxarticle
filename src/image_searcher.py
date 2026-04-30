from __future__ import annotations
"""图库搜索模块 - 从Pexels/Pixabay获取免费可商用图片

v2改进：用LLM生成精准英文搜索词，替代硬编码中文→英文映射表
- 封面图：LLM根据文章标题+内容+赛道风格生成搜索词
- 插图：LLM根据段落内容生成搜索词
- fallback：LLM失败时降级到简化版映射表
"""
import json
import re
import time
from pathlib import Path
from typing import Optional

import requests

from config import (
    PEXELS_API_KEY, PIXABAY_API_KEY,
    COVER_WIDTH, COVER_HEIGHT, OUTPUT_DIR,
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, MODEL_NAME,
)


# ==================== LLM关键词生成 ====================

# 赛道默认图片风格
TRACK_IMAGE_STYLES = {
    "感悟赛道": "warm, peaceful, contemplative, nature, soft light, lifestyle",
    "人物赛道": "portrait, dramatic light, vintage, history, documentary",
    "生活赛道": "cozy home, clean, organized, lifestyle, kitchen, bright",
    "AI赛道": "technology, futuristic, digital, blue light, abstract",
    "高校赛道": "campus, youth, study, books, classroom, energetic",
}

# 简化版映射表（仅作LLM失败的fallback）
_FALLBACK_KEYWORD_MAP = {
    "科技": "technology innovation", "人工智能": "artificial intelligence robot",
    "AI": "artificial intelligence", "互联网": "internet digital",
    "创业": "startup business", "商业": "business office",
    "婚姻": "marriage couple", "家庭": "family home",
    "孩子": "child family", "教育": "education learning",
    "朋友": "friendship together", "爱情": "love couple romantic",
    "健康": "health wellness", "心理": "mental health",
    "情绪": "emotion feeling", "压力": "stress relief",
    "幸福": "happiness joy", "孤独": "solitude thinking",
    "旅行": "travel landscape", "美食": "food cooking",
    "运动": "sports fitness", "读书": "books reading",
    "职场": "office professional", "成长": "growth success",
    "生活": "lifestyle daily", "时间": "time hourglass",
    "人生": "life journey path", "中年": "midlife balance",
    "自由": "freedom sky", "勇气": "courage mountain",
    "自然": "nature landscape", "城市": "city urban",
    "文化": "culture heritage", "历史": "history vintage",
    "科学": "science research", "选择": "choice crossroad",
    "改变": "change transformation", "梦想": "dream aspiration",
    "坚持": "persistence climb", "成功": "success achievement",
    "失败": "failure setback", "平衡": "balance harmony",
    "迷茫": "lost confusion fog", "突破": "breakthrough innovation",
    "收纳": "organization clean home", "整理": "tidy organized minimalism",
    "厨房": "kitchen cooking clean", "省钱": "saving money budget",
    "极简": "minimalism simple zen", "仪式感": "aesthetic lifestyle elegant",
}


def _get_track_image_style(track_name: str) -> str:
    """从config.yaml读取赛道的image_style，没有则用硬编码默认值"""
    try:
        from track_manager import load_config
        config = load_config()
        for track in config.get("tracks", []):
            if track["name"] == track_name:
                return track.get("image_style", "")
    except Exception:
        pass
    # fallback到硬编码默认值
    return TRACK_IMAGE_STYLES.get(track_name, "professional, clean, elegant")


def _generate_keywords_with_llm(
    article_title: str,
    article_content: str = "",
    track_name: str = "",
    image_type: str = "cover",
) -> str:
    """
    用LLM根据文章内容生成精准的英文图片搜索关键词
    
    Args:
        article_title: 文章标题
        article_content: 文章内容（封面图取前500字，插图取段落）
        track_name: 赛道名（用于确定图片风格）
        image_type: "cover" 或 "inline"
    
    Returns:
        英文搜索关键词字符串
    """
    if not SILICONFLOW_API_KEY:
        return _fallback_extract_keywords(article_title)

    # 获取赛道图片风格
    style_hint = _get_track_image_style(track_name) or "professional, clean, elegant"

    # 根据图片类型调整prompt
    if image_type == "cover":
        content_sample = article_content[:500] if article_content else ""
        prompt = f"""你是一个专业的图库搜索专家。请根据以下文章信息，生成最适合搜索封面图的英文关键词。

文章标题：{article_title}
文章内容摘要：{content_sample}
图片风格偏好：{style_hint}

要求：
1. 生成2-3个英文搜索词组，用空格分隔
2. 搜索词要能精准反映文章核心主题和意境
3. 搜索词要适合在Pexels等图库搜索，能搜到高质量相关图片
4. 风格词放在最后（如 warm, peaceful, nature 等）
5. 不要太抽象，要有具象的视觉元素（如 sunset, path, book 等）

只输出搜索关键词，不要任何解释。示例输出：sunset mountain path peaceful contemplation"""
    else:
        prompt = f"""你是一个专业的图库搜索专家。请根据以下段落内容，生成最适合搜索插图的英文关键词。

段落内容：{article_title}
图片风格偏好：{style_hint}

要求：
1. 生成2-3个英文搜索词组，用空格分隔
2. 搜索词要能反映段落核心内容的视觉画面
3. 适合在Pexels图库搜索，能搜到与内容相关的实景图片
4. 不要太抽象，要有具象的视觉元素

只输出搜索关键词，不要任何解释。"""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url=SILICONFLOW_BASE_URL)

        response = client.chat.completions.create(
            model="Qwen/Qwen3-8B",  # 用小模型生成搜索词，速度快5-10倍
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=60,  # 搜索词不需要长输出
        )

        keywords = response.choices[0].message.content.strip()
        # 清理：只保留英文、数字、空格和逗号
        keywords = re.sub(r"[^\w\s,]", "", keywords)
        # 替换逗号为空格
        keywords = keywords.replace(",", " ")
        # 压缩多个空格
        keywords = re.sub(r"\s+", " ", keywords).strip()

        if len(keywords) < 5:
            # LLM返回太短，可能出错了
            print(f"  [WARN] LLM关键词过短: {keywords}")
            return _fallback_extract_keywords(article_title)

        # 限制关键词数量：Pexels搜索3-5个词效果最好
        words = keywords.split()
        if len(words) > 6:
            # 保留前3个具象词 + 后2个风格词
            keywords = " ".join(words[:5])

        print(f"  [LLM] 生成搜索词: {keywords}")
        return keywords

    except Exception as e:
        print(f"  [WARN] LLM关键词生成失败: {e}")
        return _fallback_extract_keywords(article_title)


def _fallback_extract_keywords(title: str) -> str:
    """
    Fallback：用简化版映射表提取关键词（LLM失败时使用）
    """
    matched = []
    sorted_keys = sorted(_FALLBACK_KEYWORD_MAP.keys(), key=len, reverse=True)
    for zh_key in sorted_keys:
        if zh_key in title and _FALLBACK_KEYWORD_MAP[zh_key] not in matched:
            matched.append(_FALLBACK_KEYWORD_MAP[zh_key])
        if len(matched) >= 2:
            break

    if matched:
        return " ".join(matched)

    # 最终fallback
    import random
    fallback_options = [
        "gentle nature calm peaceful",
        "soft light warm cozy",
        "clean minimal elegant professional",
        "beautiful landscape serene",
        "inspirational morning light hope",
    ]
    return random.choice(fallback_options)


# ==================== Pexels API ====================

def search_pexels(
    query: str,
    per_page: int = 5,
    orientation: str = "landscape",
) -> list[dict]:
    """
    从Pexels搜索图片
    返回 [{"url": str, "alt": str, "photographer": str}, ...]
    
    免费额度：200次/小时，5000次/月
    """
    if not PEXELS_API_KEY:
        print("  ⚠ 未配置 PEXELS_API_KEY，跳过Pexels搜索")
        return []

    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
        "locale": "en-US",  # 改为英文区域，英文搜索词效果更好
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        if resp.status_code == 429:
            print("  ⚠ Pexels API限流")
            return []
        if resp.status_code != 200:
            print(f"  ⚠ Pexels搜索失败 (HTTP {resp.status_code})")
            return []

        data = resp.json()
        results = []
        for photo in data.get("photos", []):
            results.append({
                "url": photo["src"]["large"],
                "original": photo["src"]["original"],
                "thumb": photo["src"]["medium"],
                "alt": photo.get("alt", ""),
                "photographer": photo.get("photographer", ""),
                "width": photo.get("width", 0),
                "height": photo.get("height", 0),
            })
        return results

    except Exception as e:
        err_str = str(e)
        # 精简错误输出，避免刷屏
        if "timeout" in err_str.lower() or "timed out" in err_str.lower():
            print("  ✗ Pexels搜索超时")
        elif "SSL" in err_str or "EOF" in err_str:
            print("  ✗ Pexels SSL连接失败")
        else:
            print(f"  ✗ Pexels搜索异常: {err_str[:60]}")
        return []


# ==================== Pixabay API ====================

def search_pixabay(
    query: str,
    per_page: int = 5,
    orientation: str = "horizontal",
) -> list[dict]:
    """
    从Pixabay搜索图片
    返回 [{"url": str, "alt": str, "photographer": str}, ...]
    
    免费额度：5000次/小时，无月限制
    """
    if not PIXABAY_API_KEY:
        print("  ⚠ 未配置 PIXABAY_API_KEY，跳过Pixabay搜索")
        return []

    url = "https://pixabay.com/api/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "per_page": per_page,
        "orientation": orientation,
        "image_type": "photo",
        "lang": "en",  # 改为英文，配合英文搜索词
        "safesearch": "true",
        "min_width": 800,
    }

    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            print(f"  ⚠ Pixabay搜索失败 (HTTP {resp.status_code})")
            return []

        data = resp.json()
        results = []
        for hit in data.get("hits", []):
            results.append({
                "url": hit.get("webformatURL", hit.get("largeImageURL", "")),
                "original": hit.get("largeImageURL", hit.get("imageURL", "")),
                "thumb": hit.get("previewURL", ""),
                "alt": query,
                "photographer": hit.get("user", ""),
                "width": hit.get("imageWidth", 0),
                "height": hit.get("imageHeight", 0),
            })
        return results

    except Exception as e:
        err_str = str(e)
        if "timeout" in err_str.lower() or "timed out" in err_str.lower():
            print("  ✗ Pixabay搜索超时")
        else:
            print(f"  ✗ Pixabay搜索异常: {err_str[:60]}")
        return []


# ==================== 统一搜索 + 下载 ====================

def search_stock_images(
    query: str,
    per_page: int = 5,
    orientation: str = "landscape",
) -> list[dict]:
    """
    统一搜索接口：先搜Pexels，不够再搜Pixabay
    """
    results = []

    # 先搜Pexels（图片质量普遍更高）
    pexels_results = search_pexels(query, per_page, orientation)
    results.extend(pexels_results)

    # 不够再搜Pixabay
    if len(results) < per_page:
        remaining = per_page - len(results)
        pixabay_results = search_pixabay(query, remaining, "horizontal" if orientation == "landscape" else orientation)
        results.extend(pixabay_results)

    return results


def download_image(url: str, save_path: Path) -> bool:
    """下载图片到本地"""
    try:
        resp = requests.get(url, timeout=10, stream=True)
        if resp.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        return False
    except Exception as e:
        err_str = str(e)
        if "timeout" in err_str.lower():
            print("  ✗ 下载图片超时")
        else:
            print(f"  ✗ 下载图片失败: {err_str[:60]}")
        return False


# ==================== 封面图搜索 ====================

def search_cover_image(
    article_title: str,
    article_content: str = "",
    track_name: str = "",
) -> Optional[dict]:
    """
    根据文章标题和内容搜索封面图
    使用LLM生成精准搜索关键词
    """
    # 用LLM生成搜索关键词
    keywords = _generate_keywords_with_llm(
        article_title, article_content, track_name, image_type="cover"
    )
    
    print(f"  [SEARCH] cover keywords: {keywords}")

    results = search_stock_images(keywords, per_page=10, orientation="landscape")

    if not results:
        print("  [WARN] no cover image found")
        return None

    # 选最相关的一张（优先选第1张，因为LLM关键词已经精准了）
    # 但随机从前3张选，避免每次都是同一类图
    import random
    best = random.choice(results[:min(3, len(results))])
    return best


# ==================== 插图搜索 ====================

def search_inline_image(
    section_title: str,
    article_content: str = "",
    track_name: str = "",
    exclude_urls: set[str] | None = None,
) -> Optional[dict]:
    """
    根据段落内容搜索插图，使用LLM生成搜索词
    """
    # 用LLM生成插图搜索词
    keywords = _generate_keywords_with_llm(
        section_title, article_content, track_name, image_type="inline"
    )
    
    print(f"  [SEARCH] inline keywords: {keywords}")

    results = search_stock_images(keywords, per_page=8, orientation="landscape")

    if not results:
        return None

    # 过滤掉已使用的图片
    if exclude_urls:
        results = [r for r in results if r.get("url", "") not in exclude_urls]

    if not results:
        return None

    # 随机选择一张
    import random
    return random.choice(results[:5])


# ==================== 兼容旧接口：生成封面（改用图库搜索） ====================

def generate_cover_image(
    article_title: str,
    article_content: str,
    output_dir: Path,
    track_name: str = "",
) -> Optional[Path]:
    """
    搜索并下载封面图（替代AI生图）
    返回保存的图片路径，失败返回None
    """
    print("  [COVER] searching for cover image...")

    result = search_cover_image(article_title, article_content, track_name=track_name)
    if not result:
        # fallback到文字封面
        return _create_text_cover(article_title, output_dir)

    # 下载图片
    output_path = output_dir / "cover.jpg"
    img_url = result.get("original") or result.get("url", "")

    if img_url and download_image(img_url, output_path):
        # 调整尺寸为微信封面比例
        _resize_cover(output_path)
        print(f"  [OK] 封面图已保存: {output_path}")
        if result.get("photographer"):
            print(f"  📷 摄影师: {result['photographer']} (Pexels/Pixabay)")
        return output_path

    # 下载失败，尝试下一张
    if len(result) > 1:
        img_url = result.get("url", "")
        if img_url and download_image(img_url, output_path):
            _resize_cover(output_path)
            print(f"  [OK] 封面图已保存: {output_path}")
            return output_path

    print("  ⚠ 图库下载失败，生成文字封面")
    return _create_text_cover(article_title, output_dir)


def generate_inline_image(
    section_title: str,
    output_dir: Path,
    index: int = 1,
    exclude_urls: set[str] | None = None,
    article_content: str = "",
    track_name: str = "",
) -> Optional[Path]:
    """
    搜索并下载段落插图，支持排除已用图片URL
    """
    result = search_inline_image(
        section_title,
        article_content=article_content,
        track_name=track_name,
        exclude_urls=exclude_urls,
    )
    if not result:
        return None

    output_path = output_dir / f"inline_{index}.jpg"
    img_url = result.get("url", "")

    if img_url and download_image(img_url, output_path):
        print(f"  [OK] 插图{index}已保存: {output_path}")
        return output_path

    return None


def _resize_cover(image_path: Path) -> None:
    """将封面图裁剪为微信2.35:1比例"""
    try:
        from PIL import Image

        img = Image.open(image_path)
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        target_ratio = COVER_WIDTH / COVER_HEIGHT
        current_ratio = img.width / img.height

        if current_ratio > target_ratio:
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        elif current_ratio < target_ratio:
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))

        img = img.resize((COVER_WIDTH, COVER_HEIGHT), Image.LANCZOS)
        img.save(str(image_path), "JPEG", quality=90)

    except Exception as e:
        print(f"  ⚠ 封面裁剪失败，使用原图: {e}")


def _create_text_cover(title: str, output_dir: Path) -> Optional[Path]:
    """终极备选方案：用Pillow生成纯文字封面"""
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (COVER_WIDTH, COVER_HEIGHT), "#1a1a2e")
        draw = ImageDraw.Draw(img)

        # 渐变背景
        for y in range(COVER_HEIGHT):
            r = int(26 + (y / COVER_HEIGHT) * 40)
            g = int(26 + (y / COVER_HEIGHT) * 20)
            b = int(46 + (y / COVER_HEIGHT) * 60)
            draw.line([(0, y), (COVER_WIDTH, y)], fill=(r, g, b))

        try:
            font_large = ImageFont.truetype("msyh.ttc", 42)
            font_small = ImageFont.truetype("msyh.ttc", 20)
        except Exception:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        title_text = title[:20]
        bbox = draw.textbbox((0, 0), title_text, font=font_large)
        text_w = bbox[2] - bbox[0]
        text_x = (COVER_WIDTH - text_w) // 2
        text_y = COVER_HEIGHT // 2 - 30
        draw.text((text_x, text_y), title_text, fill="white", font=font_large)

        sub_text = "— 精选好文 —"
        bbox2 = draw.textbbox((0, 0), sub_text, font=font_small)
        sub_w = bbox2[2] - bbox2[0]
        sub_x = (COVER_WIDTH - sub_w) // 2
        draw.text((sub_x, text_y + 60), sub_text, fill="#aaaaaa", font=font_small)

        output_path = output_dir / "cover.jpg"
        img.save(str(output_path), "JPEG", quality=90)
        print(f"  [OK] 文字封面已保存: {output_path}")
        return output_path

    except Exception as e:
        print(f"  ✗ 文字封面生成也失败: {e}")
        return None


if __name__ == "__main__":
    # 测试LLM关键词生成
    print("=== 测试LLM关键词生成 ===\n")
    
    test_cases = [
        ("人到中年才明白，这三件事比赚钱更重要", "感悟赛道"),
        ("苏轼被贬黄州后的人生顿悟", "人物赛道"),
        ("厨房收纳5个小技巧，让空间翻倍", "生活赛道"),
        ("一个人开始变富的3个征兆", "感悟赛道"),
        ("被遗忘的数学家陈景润", "人物赛道"),
    ]
    
    for title, track in test_cases:
        keywords = _generate_keywords_with_llm(title, track_name=track, image_type="cover")
        print(f"  [{track}] {title}")
        print(f"  → {keywords}\n")
