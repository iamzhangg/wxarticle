from __future__ import annotations
"""封面图和插图生成模块 - 使用硅基流动图片生成API"""
import base64
import io
import time
from pathlib import Path
from typing import Optional

import requests
try:
    from PIL import Image
except ImportError:
    import sys
    print("=" * 60)
    print("[FATAL] Pillow 未安装！请运行:")
    print(f"  {sys.executable} -m pip install Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple")
    print("=" * 60)
    sys.exit(1)

from config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL,
    COVER_WIDTH, COVER_HEIGHT, OUTPUT_DIR,
)


def generate_cover_image(
    article_title: str,
    article_content: str,
    output_dir: Path,
    track_name: str = "",
) -> Optional[Path]:
    """
    使用硅基流动API生成封面图
    返回保存的图片路径，失败返回None
    """
    if not SILICONFLOW_API_KEY:
        print("  ✗ 未配置 SILICONFLOW_API_KEY，跳过封面图生成")
        return None

    # 构建图片生成提示词
    prompt = _build_cover_prompt(article_title, article_content, track_name)

    print(f"  [ART] 生成封面图...")
    print(f"  提示词: {prompt[:100]}...")

    try:
        response = requests.post(
            f"{SILICONFLOW_BASE_URL}/images/generations",
            headers={
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "Kwai-Kolors/Kolors",
                "prompt": prompt,
                "negative_prompt": "text, words, letters, Chinese characters, watermark, logo, signature, blurry, low quality, distorted",
                "image_size": "1024x1024",
                "num_inference_steps": 25,
                "guidance_scale": 7.5,
            },
            timeout=120,
        )

        if response.status_code != 200:
            print(f"  ⚠ 封面图生成失败 (HTTP {response.status_code}): {response.text[:200]}")
            # 尝试用备选模型
            return _generate_cover_fallback(prompt, output_dir)

        data = response.json()

        # 处理返回的图片
        if "images" in data and data["images"]:
            img_data = data["images"][0]
            if "url" in img_data:
                # URL方式
                img_url = img_data["url"]
                img_response = requests.get(img_url, timeout=30)
                if img_response.status_code == 200:
                    output_path = output_dir / "cover.jpg"
                    with open(output_path, "wb") as f:
                        f.write(img_response.content)
                    # 裁剪为微信2.35:1比例
                    _resize_cover(output_path)
                    print(f"  [OK] 封面图已保存: {output_path}")
                    return output_path
            elif "b64_json" in img_data:
                # Base64方式
                img_bytes = base64.b64decode(img_data["b64_json"])
                output_path = output_dir / "cover.jpg"
                with open(output_path, "wb") as f:
                    f.write(img_bytes)
                # 裁剪为微信2.35:1比例
                _resize_cover(output_path)
                print(f"  [OK] 封面图已保存: {output_path}")
                return output_path

        print(f"  ⚠ 封面图生成返回数据异常: {str(data)[:200]}")
        return _generate_cover_fallback(prompt, output_dir)

    except Exception as e:
        print(f"  ✗ 封面图生成异常: {e}")
        return _generate_cover_fallback(prompt, output_dir)


def _generate_cover_fallback(prompt: str, output_dir: Path) -> Optional[Path]:
    """备选封面图生成方案：用不同参数重试Kolors"""
    try:
        print("  🔄 重试生成封面（调整参数）...")
        response = requests.post(
            f"{SILICONFLOW_BASE_URL}/images/generations",
            headers={
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "Kwai-Kolors/Kolors",
                "prompt": prompt,
                "negative_prompt": "text, words, letters, Chinese characters, watermark, logo, signature",
                "image_size": "960x1280",
                "num_inference_steps": 20,
                "guidance_scale": 5.0,
            },
            timeout=120,
        )

        if response.status_code != 200:
            print(f"  ⚠ 备选模型也失败 (HTTP {response.status_code})")
            return _create_text_cover(prompt, output_dir)

        data = response.json()
        if "images" in data and data["images"]:
            img_data = data["images"][0]
            if "url" in img_data:
                img_response = requests.get(img_data["url"], timeout=30)
                if img_response.status_code == 200:
                    output_path = output_dir / "cover.jpg"
                    with open(output_path, "wb") as f:
                        f.write(img_response.content)
                    _resize_cover(output_path)
                    print(f"  [OK] 封面图已保存(备选参数): {output_path}")
                    return output_path

        return _create_text_cover(prompt, output_dir)

    except Exception as e:
        print(f"  ✗ 备选模型也异常: {e}")
        return _create_text_cover(prompt, output_dir)


def _resize_cover(image_path: Path) -> None:
    """将封面图裁剪为微信2.35:1比例（900x383）"""
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


# 插图目标尺寸（16:9横向长方形）
INLINE_WIDTH = 1024
INLINE_HEIGHT = 576


def _resize_inline(image_path: Path) -> None:
    """将插图裁剪为16:9横向比例（1024x576）"""
    try:
        from PIL import Image

        img = Image.open(image_path)
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        target_ratio = INLINE_WIDTH / INLINE_HEIGHT
        current_ratio = img.width / img.height

        if current_ratio > target_ratio:
            # 图片太宽，裁掉左右
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        elif current_ratio < target_ratio:
            # 图片太高，裁掉上下
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))

        img = img.resize((INLINE_WIDTH, INLINE_HEIGHT), Image.LANCZOS)
        img.save(str(image_path), "JPEG", quality=90)

    except Exception as e:
        print(f"  ⚠ 插图裁剪失败，使用原图: {e}")


def _create_text_cover(prompt_short: str, output_dir: Path) -> Optional[Path]:
    """
    终极备选方案：用Pillow生成纯文字封面
    """
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

        # 使用默认字体
        try:
            font_large = ImageFont.truetype("msyh.ttc", 42)
            font_small = ImageFont.truetype("msyh.ttc", 20)
        except Exception:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # 标题文字（取prompt前20字）
        title_text = prompt_short[:20]
        # 居中绘制
        bbox = draw.textbbox((0, 0), title_text, font=font_large)
        text_w = bbox[2] - bbox[0]
        text_x = (COVER_WIDTH - text_w) // 2
        text_y = COVER_HEIGHT // 2 - 30
        draw.text((text_x, text_y), title_text, fill="white", font=font_large)

        # 副标题
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


def _build_cover_prompt(title: str, content: str, track_name: str = "") -> str:
    """根据文章标题和内容构建封面图提示词，用LLM翻译中文为英文视觉描述"""
    # 尝试用LLM生成英文图片描述
    english_desc = _translate_to_english_visual(title, content, track_name, image_type="cover")

    if english_desc:
        prompt = (
            f"{english_desc}. "
            f"Professional, high quality, soft lighting, elegant composition, "
            f"no text, no words, no letters, no Chinese characters, no watermark. "
            f"Aspect ratio suitable for social media article cover."
        )
    else:
        # fallback
        key_text = title
        if len(key_text) < 10:
            key_text = content[:100]
        prompt = (
            f"A professional magazine cover image for an article about: {key_text[:60]}. "
            f"Modern, clean design, minimalist style, high quality, "
            f"soft lighting, elegant composition, no text, no words, no letters, no Chinese characters. "
            f"Aspect ratio suitable for social media article cover."
        )
    return prompt


# 赛道图片风格映射
_TRACK_STYLE_PROMPTS = {
    "感悟赛道": "warm, peaceful, contemplative, nature, soft light, sunrise, path",
    "人物赛道": "dramatic portrait lighting, vintage, cinematic, documentary style",
    "生活赛道": "cozy home interior, clean, organized, bright, warm sunlight, lifestyle",
    "AI赛道": "futuristic technology, digital, blue light, abstract, neon, cyber",
    "高校赛道": "campus, youth, books, study, bright morning light, energetic",
}


def _translate_to_english_visual(
    title: str, content: str, track_name: str, image_type: str = "cover"
) -> str | None:
    """用LLM将中文标题/内容翻译为英文视觉描述（用于图片生成prompt）"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url=SILICONFLOW_BASE_URL)

        style_hint = _TRACK_STYLE_PROMPTS.get(track_name, "professional, clean, elegant")

        if image_type == "cover":
            content_sample = content[:300] if content else ""
            prompt = f"""你是一个AI图片生成提示词专家。请将以下中文文章信息转化为英文图片生成描述（prompt）。

文章标题：{title}
内容摘要：{content_sample}
风格偏好：{style_hint}

要求：
1. 用英文描述一个能体现文章核心主题的视觉场景
2. 包含具象的视觉元素（如：sunlight through window, organized bookshelf, steaming coffee cup）
3. 包含风格描述（如：soft lighting, warm tone, minimalist）
4. 不要出现任何文字/字母/汉字/水印的描述
5. 输出纯英文，不要解释

示例：A cozy living room with organized shelves, warm sunlight streaming through window, soft focus, minimalist style, warm color palette"""
        else:
            prompt = f"""你是一个AI图片生成提示词专家。请将以下中文内容转化为英文图片生成描述（prompt）。

段落主题：{title}
风格偏好：{style_hint}

要求：
1. 用英文描述一个能体现内容主题的视觉场景
2. 包含具象的视觉元素
3. 包含风格描述
4. 不要出现任何文字/字母/汉字/水印的描述
5. 输出纯英文，不要解释

示例：Neatly organized kitchen counter with fresh herbs in small pots, morning light, clean and bright"""

        response = client.chat.completions.create(
            model="Qwen/Qwen3-8B",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=120,
        )

        result = response.choices[0].message.content.strip()
        # 清理：去掉多余格式
        result = result.strip('"\'').strip()
        if len(result) > 10:
            print(f"  [LLM] 图片prompt: {result[:80]}...")
            return result
        return None
    except Exception as e:
        print(f"  [WARN] LLM翻译失败: {e}")
        return None


def generate_inline_image(
    section_title: str,
    output_dir: Path,
    index: int = 1,
    exclude_urls: set[str] | None = None,
    article_content: str = "",
    track_name: str = "",
) -> Optional[Path]:
    """
    为文章段落生成插图，支持赛道风格
    """
    if not SILICONFLOW_API_KEY:
        return None

    # 用LLM翻译为英文视觉描述
    english_desc = _translate_to_english_visual(
        section_title, article_content, track_name, image_type="inline"
    )

    if english_desc:
        prompt = (
            f"{english_desc}. "
            f"Watercolor or flat design style, soft colors, "
            f"no text, no words, no letters, no Chinese characters, no watermark. "
            f"Clean and professional, suitable for WeChat article."
        )
    else:
        prompt = (
            f"An elegant illustration for a Chinese article section about: {section_title[:40]}. "
            f"Watercolor or flat design style, soft colors, no text, no words, no letters, no Chinese characters. "
            f"Clean and professional, suitable for WeChat article."
        )

    try:
        response = requests.post(
            f"{SILICONFLOW_BASE_URL}/images/generations",
            headers={
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "Kwai-Kolors/Kolors",
                "prompt": prompt,
                "negative_prompt": "text, words, letters, Chinese characters, watermark, logo, signature, blurry, low quality, distorted",
                "image_size": "1024x576",
                "num_inference_steps": 20,
                "guidance_scale": 7.5,
            },
            timeout=120,
        )

        if response.status_code == 200:
            data = response.json()
            if "images" in data and data["images"]:
                img_data = data["images"][0]
                img_url = img_data.get("url")
                if img_url:
                    img_response = requests.get(img_url, timeout=30)
                    if img_response.status_code == 200:
                        output_path = output_dir / f"inline_{index}.jpg"
                        with open(output_path, "wb") as f:
                            f.write(img_response.content)
                        # 裁剪为横向比例（确保16:9）
                        _resize_inline(output_path)
                        print(f"  [OK] 插图{index}已保存: {output_path}")
                        return output_path
        return None
    except Exception as e:
        print(f"  ⚠ 插图生成失败: {e}")
        return None
