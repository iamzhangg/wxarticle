from __future__ import annotations
"""AI文章生成模块 - 硅基流动API，卡兹克写作风格，四层自检

v2升级：支持赛道prompt + 热门选题 + khazix-writer写作风格
约束优先级：prompt > 风格skill
"""
import json
import re
import time
import requests
from pathlib import Path
from typing import Optional
from config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, MODEL_NAME,
    TARGET_WORD_COUNT, TARGET_WORD_MIN, TARGET_WORD_MAX,
)
from track_manager import get_generation_config


# ==================== 加载 khazix-writer 写作风格 ====================

def _load_khazix_skill() -> str:
    """加载khazix-writer的SKILL.md作为写作风格指南"""
    skill_paths = [
        Path.home() / ".workbuddy" / "skills" / "khazix-writer" / "SKILL.md",
        Path(__file__).parent.parent / "skills" / "khazix-writer" / "SKILL.md",
    ]
    for path in skill_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return ""


def _load_khazix_references() -> str:
    """加载khazix-writer的参考资料"""
    ref_dir_paths = [
        Path.home() / ".workbuddy" / "skills" / "khazix-writer" / "references",
        Path(__file__).parent.parent / "skills" / "khazix-writer" / "references",
    ]
    for ref_dir in ref_dir_paths:
        if not ref_dir.exists():
            continue
        texts = []
        for f in sorted(ref_dir.iterdir()):
            if f.suffix == ".md":
                with open(f, "r", encoding="utf-8") as fh:
                    texts.append(fh.read())
        if texts:
            return "\n\n---\n\n".join(texts)
    return ""


# ==================== 去AI味规则（卡兹克版，更严格） ====================

# L1 禁用词（来自khazix-writer绝对禁区）
BANNED_ZH_PHRASES = [
    # 套话
    "值得注意的是", "需要指出的是", "不可否认", "毋庸置疑", "总而言之",
    "综上所述", "在这个时代", "在当今社会", "随着时代的发展", "让我们",
    "不禁让人", "引发了广泛的", "引起了广泛的", "越来越", "不断涌现",
    "蓬勃发展", "日新月异", "瞬息万变", "方兴未艾", "如火如荼",
    "在这个背景下", "与此同时", "不仅如此", "更为重要的是", "尤为突出",
    "举足轻重", "不可或缺", "至关重要", "首当其冲", "重中之重",
    "千丝万缕", "相辅相成", "息息相关", "密不可分", "有机结合",
    "深远影响", "具有重要意义", "提供了有力支撑", "奠定了坚实基础",
    "在某种程度上", "从某种意义上说", "毋庸置疑地", "不言而喻",
    "众所周知", "可以说", "正如我们所知", "由此可见",
    # 互联网黑话
    "赋能", "降本增效", "闭环", "抓手", "打法", "链路", "沉淀",
    "矩阵", "组合拳", "破圈", "出圈", "种草", "拔草",
    "底层逻辑", "顶层设计", "赛道", "痛点", "痒点", "爽点",
    # AI味客套
    "想象一下", "让我们一起", "希望对你有所帮助", "感谢阅读",
    "今天我们来聊聊", "相信大家", "大家好", "各位朋友",
    # 卡兹克禁区词
    "说白了", "意味着什么", "这意味着", "本质上", "换句话说",
    "让我们来看看", "接下来让我们", "不难发现",
]

BANNED_EN_PHRASES = [
    "delve", "tapestry", "leverage", "harness", "utilize",
    "landscape", "multifaceted", "nuanced", "pivotal", "realm",
    "robust", "seamless", "testament", "transformative", "underscore",
    "groundbreaking", "innovative", "cutting-edge", "synergy", "holistic",
    "paradigm", "ecosystem", "crucial", "enduring", "enhance",
    "fostering", "garner", "showcase", "vibrant", "profound",
]

# L1 禁用标点
BANNED_PUNCTUATION = {
    "：": "（禁用冒号，用逗号替代）",
    "——": "（禁用破折号，用逗号或句号替代）",
}


def check_ai_flavor(text: str) -> list[str]:
    """L1-1 禁用词扫描"""
    hits = []
    text_lower = text.lower()
    for phrase in BANNED_ZH_PHRASES:
        if phrase in text:
            hits.append(phrase)
    for phrase in BANNED_EN_PHRASES:
        if phrase in text_lower:
            hits.append(phrase)
    return hits


def check_banned_punctuation(text: str) -> list[str]:
    """L1-2 禁用标点扫描"""
    hits = []
    for punct, reason in BANNED_PUNCTUATION.items():
        if punct in text:
            hits.append(f"'{punct}' {reason}")
    # 双引号检查
    if '“' in text or '”' in text:
        hits.append("禁用双引号，用「」替代")
    return hits


def check_ai_patterns(text: str) -> list[str]:
    """L1-3 + L2 结构模式检测"""
    patterns = []
    # 检测排比三连
    if re.search(r"[^\s，。！？、]{2,}、[^\s，。！？、]{2,}、[^\s，。！？、]{2,}", text):
        patterns.append("排比三连结构")
    # 检测"不仅...而且...更..."
    if re.search(r"不仅.*而且.*更", text):
        patterns.append("递进三段式")
    # 检测emoji装饰
    if re.search(r"[🔴🟢🟡[OK]❌💡[TARGET][PIN]🔥⭐🚀💰📈📉]", text):
        patterns.append("Emoji装饰")
    # 检测加粗标题列表模式
    if len(re.findall(r"\*\*[^*]+\*\*[：:]", text)) > 3:
        patterns.append("加粗标题列表模式")
    # 检测"不是X而是Y"结构过多
    if re.search(r"(?:其实|真正|关键|核心|本质)?不是.{2,10}而是", text):
        matches = re.findall(r"不是.{2,10}而是", text)
        if len(matches) >= 2:
            patterns.append("否定对仗结构")
    # 检测过度使用小标题（##）
    heading_count = len(re.findall(r"^##\s+", text, re.MULTILINE))
    if heading_count > 3:
        patterns.append(f"小标题过多({heading_count}个，应≤3)")
    # 检测句式长度过于单一
    sentences = re.split(r"[。！？]", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if len(sentences) >= 4:
        lengths = [len(s) for s in sentences[:8]]
        avg = sum(lengths) / len(lengths)
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        if variance < 4:
            patterns.append("句式长度过于单一")
    # 检测空泛工具名
    if re.search(r"(AI工具|某个模型|相关技术|某些工具)", text):
        patterns.append("空泛工具名")
    # 检测教科书开头
    first_lines = text.strip().split("\n")[:3]
    for line in first_lines:
        if re.search(r"(在当今.*的时代|随着.*的发展|在.*背景下)", line):
            patterns.append("教科书式开头")
            break

    return patterns


# ==================== 卡兹克写作风格系统提示词 ====================

def _build_khazix_system_prompt() -> str:
    """构建基于khazix-writer skill的系统提示词"""
    skill_content = _load_khazix_skill()
    ref_content = _load_khazix_references()

    if not skill_content:
        # 降级：使用内置精简版
        return _FALLBACK_SYSTEM_PROMPT

    # 使用完整的skill内容作为系统提示词
    # 截取核心写作规则部分（去掉frontmatter）
    if skill_content.startswith("---"):
        parts = skill_content.split("---", 2)
        if len(parts) >= 3:
            skill_content = parts[2].strip()

    system_prompt = f"""你正在以「数字生命卡兹克」的身份写一篇公众号长文。

⚠️ 优先级声明：以下写作风格指南是你的默认写作方式，但在用户prompt中有明确不同要求时，以prompt为准。优先级：prompt > 参考文章结构 > 本风格指南。

以下是你的完整写作风格指南：

{skill_content}
"""

    # 如果有参考资料，追加
    if ref_content:
        system_prompt += f"""

## 风格参考资料

{ref_content}
"""

    return system_prompt


# 降级用的精简版系统提示词
_FALLBACK_SYSTEM_PROMPT = """你正在以「数字生命卡兹克」的身份写一篇公众号长文。

⚠️ 优先级声明：以下写作风格指南是你的默认写作方式，但在用户prompt中有明确不同要求时，以prompt为准。优先级：prompt > 参考文章结构 > 本风格指南。

风格一句话概括：「有见识的普通人在认真聊一件打动他的事。」

## 核心原则
1. 讲人话，像个活人。大胆使用"我觉得""我认为"
2. 真诚是唯一的捷径。可以不写，但绝不骗人
3. 永远对世界保持好奇

## 绝对禁区
1. 禁用套话："首先...其次...最后"、"综上所述"、"值得注意的是"
2. 不用bullet point罗列，不加小标题，靠口语化转场自然推进
3. 禁用冒号"："、破折号"——"、双引号"" ""。用逗号替代冒号和破折号，用「」替代双引号
4. 禁用："说白了"、"意味着什么"、"这意味着"、"本质上"、"换句话说"、"不可否认"
5. 不编造假设性例子，不空泛提"AI工具"要说具体名字
6. 禁止"在当今时代"类宏大叙事开头

## 风格内核
- 节奏感：长短句交替，一句话自成一段制造重点
- 论述中故意打破：重复强调、中途打断、省略主语
- 知识是"聊着聊着顺手掏出来"的
- 私人视角："我也面临这个问题"
- 敢下判断，但先理解对立面
- 情绪表达："。。。""？？？""= ="
- 句式断裂：极短句独立成段
- 回环呼应：前面埋钩子，后面callback

## 结构
【开头】具体事件切入 → 【背景】聊天式科普 → 【核心】分板块展开，有观点+场景+私人连接+扣主线句 → 【升华】文化/哲学连接 → 【收尾】五种收法选一 → 【尾部】三连+签名

## 推荐口语化
坦率的讲、说真的、怎么说呢、其实吧、你想想看、我跟你说、我有时候觉得、说实话我也不确定、这种感觉太爽了、太离谱了、这玩意、不是哥们、真的就是一声叹息
"""


# ==================== v2: 赛道感知的文章生成 ====================

def build_track_aware_prompt(
    track_prompt: str,
    hot_topic: dict,
) -> str:
    """
    构建赛道感知的文章生成prompt（v2核心）

    两层约束体系（冲突时按此优先级）：
    1. 【最高】prompt（赛道写作约束）— 强制规范，不可违反
    2. 【最低】风格skill（khazix-writer）— 写作风格建议

    Args:
        track_prompt: 赛道的prompt.md内容（最高优先级）
        hot_topic: 热门选题 {"title": str, "angle": str, ...}
    """
    # 读取生成配置
    gen_config = get_generation_config()
    word_min = gen_config.get("word_count_min", TARGET_WORD_MIN)
    word_max = gen_config.get("word_count_max", TARGET_WORD_MAX)

    prompt = f"""请根据以下信息，创作一篇全新的公众号长文。

⚠️ 【两层约束优先级】当以下规则有冲突时，严格按照此优先级执行：
- 第一优先级（不可违反）：赛道写作约束（prompt）
- 第二优先级（风格建议）：系统提示词中的写作风格指南
→ prompt的规则 > 风格skill的建议

## 今日选题

热门话题：{hot_topic.get("original_topic", hot_topic.get("title", ""))}
拟定标题：{hot_topic.get("title", "")}
切入角度：{hot_topic.get("angle", "自由发挥")}

## 【第一优先级】赛道写作约束（必须遵守，不可违反）

{track_prompt if track_prompt else "（使用默认写作约束）"}

## 创作要求

1. **prompt至上**：赛道写作约束中的规则是硬性要求，如果与风格建议冲突，以prompt为准
2. **风格作为底色**：系统提示词中的写作风格是你默认的写作方式，但遇到prompt有明确不同要求时，以prompt为准
3. **字数目标**：{word_min}-{word_max}字，严格遵守
4. **四层自检**：写完后自行跑一遍L1硬性规则检查，确保禁用词和禁用标点零命中
5. **格式**：直接输出Markdown格式，第一行是标题（# 标题），然后是正文。不加小标题（除非prompt中明确要求，或分条目的方法论文章）
6. **排版加粗**：正文中适当使用**加粗**标记关键短语、核心观点、转折处，每段至少1-2处加粗，让文章有视觉节奏感。加粗内容应该是真正值得强调的词句，不要整句加粗

请直接输出文章内容，不要输出任何解释或前言。"""

    return prompt


def generate_article(
    track_prompt: str = "",
    hot_topic: dict = None,
    target_word_count: int = TARGET_WORD_COUNT,
    max_retries: int = 5,
) -> Optional[dict]:
    """
    生成新文章（v2赛道感知版 + khazix-writer风格）

    Args:
        track_prompt: 赛道的prompt.md内容
        hot_topic: 热门选题信息
        target_word_count: 目标字数
        max_retries: 最大重试次数

    Returns:
        {"title": str, "content": str, "summary": str, ...} 或 None
    """
    if not SILICONFLOW_API_KEY:
        print("  [ERROR] SILICONFLOW_API_KEY not configured")
        return None

    # 读取生成配置
    gen_config = get_generation_config()
    model = gen_config.get("model", MODEL_NAME)
    word_min = gen_config.get("word_count_min", TARGET_WORD_MIN)
    word_max = gen_config.get("word_count_max", TARGET_WORD_MAX)

    # 构建prompt
    if hot_topic:
        prompt = build_track_aware_prompt(track_prompt, hot_topic)
    else:
        prompt = _build_simple_prompt(track_prompt, word_min, word_max)

    # 系统提示词：使用khazix-writer完整风格指南
    system_prompt = _build_khazix_system_prompt()

    for attempt in range(1, max_retries + 1):
        print(f"  [GEN] attempt {attempt}/{max_retries}...")

        try:
            resp = requests.post(
                f"{SILICONFLOW_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.75,
                    "max_tokens": 8000,
                    "top_p": 0.85,
                },
                timeout=300,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"].strip()
            if not raw_content:
                print("  [WARN] empty response, retrying...")
                continue

            # 提取标题
            title = "未命名文章"
            content = raw_content
            lines = raw_content.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("# ") and len(line) > 3:
                    title = line.lstrip("# ").strip()
                    content = "\n".join(lines[1:]).strip()
                    break

            # 字数检查
            word_count = len(content)
            if word_count > word_max:
                print(f"  [TRIM] {word_count} chars > {word_max}, trimming...")
                content = _smart_truncate(content, word_min, word_max)
                raw_content = f"# {title}\n\n{content}"
                word_count = len(content)
                print(f"  [TRIM] after trim: {word_count} chars")
            elif word_count < word_min:
                print(f"  [WARN] {word_count} chars < {word_min}, too short, retrying...")
                prompt += f"\n\n## 要求\n上一次生成只有{word_count}字，太短了。请扩展内容到{word_min}-{word_max}字。多用具体场景和人物来展开观点。"
                continue

            # L1 硬性规则检查
            ai_hits = check_ai_flavor(raw_content)
            punct_hits = check_banned_punctuation(raw_content)
            ai_patterns = check_ai_patterns(raw_content)

            total_l1_hits = len(ai_hits) + len(punct_hits) + len(ai_patterns)

            print(f"  [L1] 禁用词: {len(ai_hits)}, 禁用标点: {len(punct_hits)}, 结构问题: {len(ai_patterns)}, 字数: {word_count}")

            # L1不过，重试
            if total_l1_hits > 5 or len(ai_patterns) > 3:
                print("  [WARN] L1检查未通过，retrying with corrections...")
                corrections = []
                if ai_hits:
                    corrections.append("禁用词：" + "、".join(ai_hits[:10]))
                if punct_hits:
                    corrections.append("禁用标点：" + "、".join(punct_hits[:5]))
                if ai_patterns:
                    corrections.append("结构问题：" + "、".join(ai_patterns))
                prompt += "\n\n## 上次L1检查问题\n请修复以下问题后重写：" + "；".join(corrections)
                prompt += "\n\n记住：冒号用逗号替代，破折号用逗号或句号替代，双引号用「」替代。"
                continue

            # 自动修复L1小问题（少量禁用词/标点）
            if total_l1_hits > 0 and total_l1_hits <= 5:
                raw_content = _auto_fix_l1_issues(raw_content)
                content = raw_content
                # 重新提取标题
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("# ") and len(line) > 3:
                        title = line.lstrip("# ").strip()
                        content = "\n".join(content.split("\n")[1:]).strip()
                        break

            # 生成简介
            from openai import OpenAI
            ai_client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url=SILICONFLOW_BASE_URL)
            summary = _generate_summary(ai_client, title, content)

            return {
                "title": title,
                "content": content,
                "raw_markdown": raw_content,
                "summary": summary,
                "ai_flavor_hits": ai_hits,
                "ai_pattern_hits": ai_patterns,
            }

        except Exception as e:
            print(f"  [ERROR] generation failed: {e}")
            time.sleep(2)

    print("  [ERROR] max retries reached, generation failed")
    return None


def _auto_fix_l1_issues(text: str) -> str:
    """自动修复L1小问题（少量禁用标点和禁用词）"""
    # 修复禁用标点
    text = text.replace("：", "，")
    text = text.replace("——", "，")
    # 修复双引号
    text = text.replace('“', '「').replace('”', '」')

    # 修复最常见的禁用词
    replacements = {
        "说白了": "坦率的讲",
        "这意味着": "所以呢",
        "意味着什么": "那结果会怎样呢",
        "本质上": "说到底",
        "换句话说": "你想想看",
        "不可否认": "",
        "综上所述": "说到底",
        "值得注意的是": "",
        "不难发现": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def _generate_summary(client, title: str, content: str) -> str:
    """用AI生成文章简介（≤120字）"""
    try:
        response = client.chat.completions.create(
            model="Qwen/Qwen3-8B",
            messages=[
                {"role": "system", "content": "你是一个文章摘要生成器。请为给定文章生成一段简洁的简介，不超过120字，直接输出简介文本，不要任何格式。用聊天式的口吻，不要像摘要。"},
                {"role": "user", "content": f"标题：{title}\n\n正文：{content[:1000]}"},
            ],
            temperature=0.5,
            max_tokens=200,
        )
        summary = response.choices[0].message.content.strip()
        if len(summary) > 120:
            summary = summary[:117] + "..."
        return summary
    except Exception:
        return content[:100].strip() + "..."


def _build_simple_prompt(track_prompt: str, word_min: int, word_max: int) -> str:
    """无热点选题时的简单prompt构建"""
    prompt_text = track_prompt if track_prompt else "（使用默认写作约束）"
    return f"""请创作一篇全新的公众号长文。

## 赛道写作约束

{prompt_text}

## 创作要求

1. **字数目标**：{word_min}-{word_max}字
2. **去AI味**：用真人说话的口吻写
3. **四层自检**：确保禁用词和禁用标点零命中
4. **格式**：直接输出Markdown格式，包含标题、正文

请直接输出文章内容。"""


def _smart_truncate(text: str, min_len: int, max_len: int) -> str:
    """智能截断文章到目标字数范围"""
    if min_len <= len(text) <= max_len:
        return text

    target = (min_len + max_len) // 2
    paragraphs = text.split("\n\n")
    result = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2
        if current_len + para_len > target and current_len >= min_len:
            break
        result.append(para)
        current_len += para_len

    truncated = "\n\n".join(result)

    if len(truncated) > max_len:
        truncated = truncated[:max_len]
        for i in range(len(truncated) - 1, max(len(truncated) - 100, 0), -1):
            if truncated[i] in "。！？":
                truncated = truncated[:i + 1]
                break

    if len(truncated) < min_len and len(paragraphs) > len(result):
        next_para = paragraphs[len(result)]
        truncated += "\n\n" + next_para
        if len(truncated) > max_len:
            truncated = truncated[:max_len]
            for i in range(len(truncated) - 1, max(len(truncated) - 100, 0), -1):
                if truncated[i] in "。！？":
                    truncated = truncated[:i + 1]
                    break

    return truncated


if __name__ == "__main__":
    result = generate_article(track_prompt="测试赛道prompt", hot_topic={"title": "测试选题", "angle": "测试角度"})
    if result:
        print(f"\n标题: {result['title']}")
        print(f"简介: {result.get('summary', '')}")
        print(f"字数: {len(result['content'])}")
