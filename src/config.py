from __future__ import annotations
"""配置模块 - 从 .env 文件和 config.yaml 加载配置

v2: 新增config.yaml赛道配置支持，保留.env的API密钥管理
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env
ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
INPUT_DIR = PROJECT_ROOT / "input_articles"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
TRACKS_DIR = PROJECT_ROOT / "tracks"

# 硅基流动 API
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3-235B-A22B-Instruct-2507")

# 图库 API（免费可商用）
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

# SM.MS 图床
SMMS_TOKEN = os.getenv("SMMS_TOKEN", "")

# 图片来源模式：优先读环境变量，其次读config.yaml，默认stock
_yaml_gen_config = {}
try:
    import yaml as _yaml
    _cfg_path = Path(__file__).parent.parent / "config.yaml"
    if _cfg_path.exists():
        with open(_cfg_path, "r", encoding="utf-8") as _f:
            _yaml_gen_config = _yaml.safe_load(_f).get("generation", {})
except Exception:
    pass
IMAGE_SOURCE = os.getenv("IMAGE_SOURCE", _yaml_gen_config.get("image_source", "stock"))

# 封面图配置
COVER_WIDTH = 900
COVER_HEIGHT = 383  # 微信公众号2.35:1比例

# 文章生成配置（默认值，可被config.yaml覆盖）
MAX_REFERENCE_ARTICLES = 5
TARGET_WORD_COUNT = 1250
TARGET_WORD_MIN = 1200
TARGET_WORD_MAX = 1300
MAX_SIMILARITY = 0.10

# 插图配置（优先读环境变量，其次读config.yaml）
MIN_CHARS_BETWEEN_IMAGES = int(os.getenv("MIN_CHARS_BETWEEN_IMAGES", _yaml_gen_config.get("min_chars_between_images", "300")))
INLINE_IMAGE_COUNT = int(os.getenv("INLINE_IMAGE_COUNT", _yaml_gen_config.get("inline_image_count", "3")))

# 公众号抓取配置（v1遗留，v2不再使用）
DEFAULT_ACCOUNT = os.getenv("DEFAULT_ACCOUNT", "")
SCRAPE_MAX_ARTICLES = int(os.getenv("SCRAPE_MAX_ARTICLES", "5"))
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "86400"))
