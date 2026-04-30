from __future__ import annotations
"""
赛道管理模块 - 读取赛道配置、prompt、参考文章

赛道目录结构：
  tracks/
  ├── 情感赛道/
  │   └── prompt.md      # 写作约束
  ├── AI赛道/
  └── 高校赛道/
"""
import yaml
from pathlib import Path
from typing import Optional

from article_parser import parse_article


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
TRACKS_DIR = PROJECT_ROOT / "tracks"


def load_config() -> dict:
    """加载 config.yaml 配置"""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_enabled_tracks() -> list[dict]:
    """获取所有启用的赛道配置"""
    config = load_config()
    tracks = config.get("tracks", [])
    return [t for t in tracks if t.get("enabled", True)]


def get_track_dir(track_name: str) -> Path:
    """获取赛道目录路径"""
    return TRACKS_DIR / track_name


def load_track_prompt(track_name: str) -> str:
    """读取赛道的 prompt.md 内容"""
    prompt_path = get_track_dir(track_name) / "prompt.md"
    if not prompt_path.exists():
        print(f"  ⚠ 赛道 '{track_name}' 没有 prompt.md，使用默认写作约束")
        return ""

    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_track_samples(track_name: str, max_count: int = 5) -> list[dict]:
    """
    读取赛道的参考文章
    返回 [{"title": str, "content": str, "filepath": str}, ...]
    """
    samples_dir = get_track_dir(track_name) / "samples"
    if not samples_dir.exists():
        print(f"  ⚠ 赛道 '{track_name}' 没有 samples/ 目录")
        return []

    # 支持的文件格式
    supported_exts = {".html", ".htm", ".mhtml", ".mht", ".docx", ".md", ".markdown", ".txt"}

    files = []
    for f in samples_dir.iterdir():
        if f.is_file() and f.suffix.lower() in supported_exts:
            files.append(f)

    if not files:
        print(f"  ⚠ 赛道 '{track_name}' 的 samples/ 目录为空")
        return []

    # 按修改时间倒序
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    files = files[:max_count]

    articles = []
    for f in files:
        print(f"  [REF] 解析参考文章: {f.name}")
        result = parse_article(f)
        if result:
            articles.append(result)

    print(f"  [OK] 赛道 '{track_name}' 加载了 {len(articles)} 篇参考文章")
    return articles


def get_track_keywords(track_name: str) -> list[str]:
    """获取赛道的搜索关键词"""
    config = load_config()
    for track in config.get("tracks", []):
        if track["name"] == track_name:
            return track.get("keywords", [])
    return []


def get_track_search_sources(track_name: str) -> list[str]:
    """获取赛道的选题搜索来源"""
    config = load_config()
    for track in config.get("tracks", []):
        if track["name"] == track_name:
            return track.get("search_sources", ["toutiao", "weixin"])
    return ["toutiao", "weixin"]


def get_generation_config() -> dict:
    """获取生成配置"""
    config = load_config()
    return config.get("generation", {})


def get_notify_config() -> dict:
    """获取推送配置（兼容旧代码）"""
    config = load_config()
    return config.get("notify", {})


def get_schedule_config() -> dict:
    """获取定时配置"""
    config = load_config()
    return config.get("schedule", {})


def save_config(config: dict) -> None:
    """保存配置到 config.yaml"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_web_config() -> dict:
    """获取Web控制台配置"""
    config = load_config()
    return config.get("web", {})


if __name__ == "__main__":
    # 测试
    print("=== 赛道管理测试 ===\n")

    tracks = get_enabled_tracks()
    print(f"启用的赛道: {[t['name'] for t in tracks]}\n")

    for track in tracks:
        name = track["name"]
        print(f"\n--- {name} ---")
        print(f"  关键词: {get_track_keywords(name)}")
        print(f"  搜索源: {get_track_search_sources(name)}")

        prompt = load_track_prompt(name)
        print(f"  Prompt: {prompt[:80]}...")

        samples = load_track_samples(name)
        print(f"  参考文章: {len(samples)} 篇")

    gen_config = get_generation_config()
    print(f"\n生成配置: {gen_config}")
