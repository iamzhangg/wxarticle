from __future__ import annotations
#!/usr/bin/env python3
"""
wxarticle v2 - 内容平台文章自动生成工具（赛道制）

主流程：
1. 读取所有启用的赛道（config.yaml）
2. 每个赛道：
   a. 读取赛道 prompt.md + 参考文章 samples/
   b. 根据赛道关键词搜索当日热门选题
   c. AI根据赛道prompt + 热门选题撰写文章
   d. 配图 + 排版 + 上传图床
   e. 输出：封面图 + 标题简介 + 可粘贴HTML
3. 通过Web控制台查看/下载（http://localhost:8080）

用法：
    python main.py                    # 所有赛道，完整流程
    python main.py --track 情感赛道     # 只跑指定赛道
    python main.py --dry-run          # 测试模式
    python main.py --skip-search      # 跳过选题搜索，用默认选题
    python web_app.py                  # 启动Web控制台
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows终端UTF-8支持
if sys.platform == "win32":
    os.system("")
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 确保src目录在path中
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, IMAGE_SOURCE, INLINE_IMAGE_COUNT

from track_manager import (
    get_enabled_tracks, load_track_prompt,
    get_track_keywords, get_track_search_sources, get_generation_config,
)
from topic_searcher import search_hot_topics, select_best_topic
from article_generator import generate_article
from formatter import markdown_to_platform_html, save_article_files, generate_preview_html

# 根据图片来源配置选择模块
if IMAGE_SOURCE == "ai":
    from image_generator import generate_cover_image, generate_inline_image
else:
    from image_searcher import generate_cover_image, generate_inline_image


def _normalize_pre_assigned_dirs(raw_dirs: dict | None) -> dict[str, list[Path]]:
    """Normalize legacy {track: path} and current {track: [paths]} formats."""
    if not raw_dirs:
        return {}

    normalized = {}
    for track_name, value in raw_dirs.items():
        if isinstance(value, list):
            normalized[track_name] = [Path(v) for v in value]
        else:
            normalized[track_name] = [Path(value)]
    return normalized


def _extract_image_topics(title: str, content: str) -> list[str]:
    """从文章标题和内容中提取插图搜索主题词"""
    import re
    topics = []

    paragraphs = [p.strip() for p in content.split("\n") if p.strip() and len(p.strip()) > 20]

    scene_words = []
    for para in paragraphs:
        words = re.findall(r'[\u4e00-\u9fff]{2,6}', para)
        for w in words:
            if w not in ("的是", "不是", "就是", "还是", "也是", "都是",
                         "一个", "那种", "这种", "什么", "怎么",
                         "可以", "已经", "后来", "当时", "现在",
                         "自己", "别人", "他们", "我们", "她们",
                         "没有", "有人", "有些", "那些", "这些"):
                scene_words.append(w)

    seen = set()
    unique_words = []
    for w in scene_words:
        if w not in seen:
            seen.add(w)
            unique_words.append(w)

    if len(unique_words) >= 5:
        step = len(unique_words) // 5
        for i in range(0, len(unique_words), step):
            if len(topics) >= INLINE_IMAGE_COUNT + 1:
                break
            topics.append(unique_words[i])
    else:
        topics.extend(unique_words[:INLINE_IMAGE_COUNT + 1])

    if not topics:
        topics.append(title)

    return topics[:INLINE_IMAGE_COUNT + 1]


def _get_next_output_dir(date_str: str, track_name: str) -> Path:
    """获取下一个可用的输出目录（支持同赛道同天多篇文章）

    命名规则：第一篇为 赛道名，后续为 赛道名_2, 赛道名_3...
    """
    date_dir = OUTPUT_DIR / date_str
    if not date_dir.exists():
        return date_dir / track_name

    # 检查是否已有同名目录
    if not (date_dir / track_name).exists():
        return date_dir / track_name

    # 找下一个可用序号
    seq = 2
    while (date_dir / f"{track_name}_{seq}").exists():
        seq += 1
    return date_dir / f"{track_name}_{seq}"


def process_track(
    track: dict,
    dry_run: bool = False,
    skip_search: bool = False,
    output_dir: Path | None = None,
) -> dict | None:
    """
    处理单个赛道的文章生成流程

    Args:
        track: 赛道配置 {"name": str, "keywords": [...], ...}
        dry_run: 测试模式
        skip_search: 跳过选题搜索

    Returns:
        生成结果字典，或None
    """
    track_name = track["name"]
    print(f"\n{'='*50}")
    print(f"🏁 赛道: {track_name}")
    print(f"{'='*50}")

    # ========== Step 1: 读取赛道配置 ==========
    print(f"\n[INFO] Step 1: 读取赛道配置...")
    track_prompt = load_track_prompt(track_name)
    keywords = get_track_keywords(track_name)

    print(f"  Prompt: {'已加载' if track_prompt else '无（使用默认）'}")
    print(f"  关键词: {keywords}")

    # ========== Step 2: 搜索热门选题 ==========
    print(f"\n[SEARCH] Step 2: 搜索热门选题...")
    hot_topic = None

    if not dry_run and not skip_search:
        sources = get_track_search_sources(track_name)
        topics = search_hot_topics(keywords, sources=sources, count=15)

        if topics:
            print(f"  找到 {len(topics)} 个相关选题")
            # AI筛选最佳选题
            hot_topic = select_best_topic(track_name, track_prompt, topics)
            if hot_topic:
                print(f"  [OK] 选定选题: {hot_topic.get('title', '')}")
                print(f"  [TARGET] 切入角度: {hot_topic.get('angle', '')}")
                print(f"  [PIN] 基于热点: {hot_topic.get('original_topic', '')}")
            else:
                print(f"  ⚠ AI选题筛选失败，使用默认选题")
        else:
            print(f"  ⚠ 未搜索到热门选题，使用默认选题")

    # 降级选题
    if not hot_topic:
        hot_topic = {
            "title": f"{track_name}：今日话题",
            "angle": "自由发挥",
            "original_topic": keywords[0] if keywords else track_name,
        }

    # ========== Step 3: AI生成文章 ==========
    print(f"\n✍️ Step 3: AI生成文章...")

    if dry_run:
        article = {
            "title": f"【测试】{hot_topic.get('title', '测试文章')}",
            "content": "这是测试内容，用于验证流程。" * 50,
            "raw_markdown": f"# 【测试】{hot_topic.get('title', '测试文章')}\n\n" + "这是测试内容，用于验证流程。" * 50,
            "summary": "这是测试文章的简介，用于验证流程是否正常。",
            "ai_flavor_hits": [],
            "ai_pattern_hits": [],
        }
    else:
        article = generate_article(
            track_prompt=track_prompt,
            hot_topic=hot_topic,
        )
        if not article:
            print(f"  ✗ 文章生成失败")
            return None

    print(f"  [WRITE] 标题: {article['title']}")
    print(f"  [WRITE] 简介: {article.get('summary', '无')[:50]}...")
    print(f"  📏 字数: {len(article['content'])}")

    # ========== Step 4: 配图 ==========
    print(f"\n[ART] Step 4: 生成封面图和插图...")

    date_str = datetime.now().strftime("%Y-%m-%d")
    # 支持同赛道同天多篇文章：赛道名_序号
    if output_dir:
        track_output_dir = output_dir
    else:
        track_output_dir = _get_next_output_dir(date_str, track_name)
    track_output_dir.mkdir(parents=True, exist_ok=True)

    cover_path = None
    inline_images = []  # 存储在线URL

    if not dry_run:
        # 封面图
        cover_path = generate_cover_image(
            article["title"],
            article["content"],
            track_output_dir,
            track_name=track_name,
        )

        # 插图：用LLM生成搜索词替代随机中文词提取
        search_topics = _extract_image_topics(article["title"], article["content"])
        used_image_urls: set[str] = set()

        local_inline_images = []  # 本地路径，后续上传
        for i, topic in enumerate(search_topics[:INLINE_IMAGE_COUNT]):
            img_path = generate_inline_image(
                topic, track_output_dir, i + 1, exclude_urls=used_image_urls,
                article_content=article["content"], track_name=track_name,
            )
            if img_path:
                local_inline_images.append(str(img_path))

        # 补充插图：用LLM生成更多搜索词
        while len(local_inline_images) < INLINE_IMAGE_COUNT:
            fallback_topic = article["title"]  # 直接用标题，LLM会重新生成搜索词
            img_path = generate_inline_image(
                fallback_topic, track_output_dir, len(local_inline_images) + 1,
                exclude_urls=used_image_urls,
                article_content=article["content"], track_name=track_name,
            )
            if img_path:
                local_inline_images.append(str(img_path))
            else:
                break

        # ========== Step 5: 排版HTML（图片base64内嵌，不需要图床） ==========
        print(f"\n📐 Step 5: 排版为内容平台HTML...")

        cover_url = str(cover_path) if cover_path else ""
        html_content = markdown_to_platform_html(
            article["raw_markdown"],
            title=article["title"],
            cover_image_url=cover_url,
            inline_images=local_inline_images,
            output_dir=track_output_dir,
        )

    else:
        # dry-run模式
        cover_url = ""
        html_content = markdown_to_platform_html(
            article["raw_markdown"],
            title=article["title"],
            cover_image_url="",
            inline_images=[],
        )

    # ========== Step 6: 保存文件 ==========
    print(f"\n💾 Step 6: 保存文件...")

    files = save_article_files(article, html_content, track_output_dir, cover_path)

    # 更新meta.json，增加赛道和简介信息
    meta_path = track_output_dir / "meta.json"
    meta = {
        "track": track_name,
        "title": article["title"],
        "summary": article.get("summary", ""),
        "word_count": len(article["content"]),
        "hot_topic": hot_topic,
        "cover_image": str(cover_path) if cover_path else None,
        "generated_at": datetime.now().isoformat(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"  [OK] 文件已保存到: {track_output_dir}")

    return {
        "track": track_name,
        "title": article["title"],
        "summary": article.get("summary", ""),
        "cover_path": cover_path,
        "html_path": files.get("content_html"),
        "output_dir": track_output_dir,
    }


def main(
    dry_run: bool = False,
    track_name: str = "",
    skip_search: bool = False,
    pre_assigned_dirs: dict | None = None,
) -> bool:
    """v2主流程"""
    start_time = time.time()

    print("=" * 60)
    print("[BELL] wxarticle v2 - 内容平台文章自动生成（赛道制）")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 获取启用的赛道
    all_tracks = get_enabled_tracks()

    if not all_tracks:
        print("✗ 没有启用的赛道，请检查 config.yaml")
        return False

    # 如果指定了赛道，只跑该赛道
    if track_name:
        all_tracks = [t for t in all_tracks if t["name"] == track_name]
        if not all_tracks:
            print(f"✗ 未找到赛道: {track_name}")
            return False

    total_tasks = sum(max(1, int(t.get("articles_per_day", 1) or 1)) for t in all_tracks)
    assigned_dirs = _normalize_pre_assigned_dirs(pre_assigned_dirs)

    print(f"\n[STAT] 今日任务: {len(all_tracks)} 个赛道，共 {total_tasks} 篇文章")
    for t in all_tracks:
        article_count = max(1, int(t.get("articles_per_day", 1) or 1))
        print(f"  - {t['name']} × {article_count} (关键词: {', '.join(t.get('keywords', [])[:3])}...)")

    # 逐赛道处理
    results = []
    for track in all_tracks:
        article_count = max(1, int(track.get("articles_per_day", 1) or 1))
        track_dirs = assigned_dirs.get(track["name"], [])
        for article_index in range(article_count):
            try:
                out_dir = track_dirs[article_index] if article_index < len(track_dirs) else None
                if article_count > 1:
                    print(f"\n[INFO] {track['name']} 第 {article_index + 1}/{article_count} 篇")
                result = process_track(track, dry_run=dry_run, skip_search=skip_search, output_dir=out_dir)
                if result:
                    results.append(result)
            except Exception as e:
                print(f"  ✗ 赛道 '{track['name']}' 第 {article_index + 1} 篇处理失败: {e}")
                import traceback
                traceback.print_exc()

    # ========== 完成 ==========
    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"[OK] 完成！总耗时: {elapsed:.1f}秒")
    print(f"   成功生成: {len(results)}/{total_tasks} 篇文章")
    for r in results:
        print(f"   [WRITE] {r['track']}: {r['title']}")
    print(f"   输出目录: {OUTPUT_DIR / datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'=' * 60}")

    return len(results) > 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="wxarticle v2 - 内容平台文章自动生成（赛道制）")
    parser.add_argument("--track", type=str, default="", help="只运行指定赛道")
    parser.add_argument("--dry-run", action="store_true", help="测试模式，不调用API")
    parser.add_argument("--skip-search", action="store_true", help="跳过选题搜索，用默认选题")
    args = parser.parse_args()

    # 从环境变量读取预分配目录（Web控制台通过子进程调用时传入）
    pre_assigned = None
    env_dirs = os.environ.get("WX_PRE_ASSIGNED_DIRS", "")
    if env_dirs:
        try:
            pre_assigned = json.loads(env_dirs)
            print(f"[INFO] 使用预分配目录: {pre_assigned}")
        except Exception as e:
            print(f"[WARN] 解析 WX_PRE_ASSIGNED_DIRS 失败: {e}")

    success = main(
        dry_run=args.dry_run,
        track_name=args.track,
        skip_search=args.skip_search,
        pre_assigned_dirs=pre_assigned,
    )
    sys.exit(0 if success else 1)
