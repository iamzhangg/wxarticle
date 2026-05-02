from __future__ import annotations
"""
热门选题搜索模块 - 从今日头条/搜狗微信搜索当日热门选题

搜索策略：
1. 根据赛道关键词，在今日头条搜索热门文章标题
2. 备选：通过搜狗微信搜索相关文章标题
3. 用AI从搜索结果中筛选出最适合该赛道的选题
"""
import json
import random
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from config import SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, MODEL_NAME


# ==================== 今日头条搜索 ====================

class ToutiaoSearcher:
    """今日头条热搜/搜索"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.toutiao.com/",
        })

    def search(self, keyword: str, count: int = 10) -> list[dict]:
        """
        搜索头条文章标题
        返回 [{"title": str, "source": "toutiao"}, ...]
        """
        results = []

        # 方法1: 头条搜索API（可能需要签名，做容错处理）
        try:
            api_results = self._search_via_api(keyword, count)
            results.extend(api_results)
        except Exception as e:
            print(f"  [WARN] 头条API搜索失败: {e}")

        # 方法2: 如果API失败，用头条热搜页面抓取
        if not results:
            try:
                page_results = self._search_via_page(keyword, count)
                results.extend(page_results)
            except Exception as e:
                print(f"  [WARN] 头条页面搜索失败: {e}")

        return results[:count]

    def _search_via_api(self, keyword: str, count: int) -> list[dict]:
        """通过头条搜索API搜索"""
        url = "https://www.toutiao.com/api/search/content/"
        params = {
            "keyword": keyword,
            "count": count,
            "cur_tab": 1,     # 综合
            "search_id": "",
            "offset": 0,
        }

        resp = self.session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return []

        data = resp.json()
        results = []

        for item in data.get("data", []):
            title = item.get("title", "")
            if title and len(title) > 5:
                results.append({
                    "title": title.strip(),
                    "source": "toutiao",
                    "abstract": item.get("abstract", "")[:200],
                })

        return results

    def _search_via_page(self, keyword: str, count: int) -> list[dict]:
        """通过头条搜索页面抓取（降级方案）"""
        search_url = f"https://www.toutiao.com/search/?keyword={quote(keyword)}"
        resp = self.session.get(search_url, timeout=15)
        if resp.status_code != 200:
            return []

        # 头条页面是SSR+CSR混合，尝试从SSR内容中提取
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        results = []
        # 尝试从script标签中提取数据
        for script in soup.find_all("script"):
            text = script.string or ""
            if "title" in text and keyword in text:
                # 尝试提取JSON数据
                try:
                    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', text, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        # 从搜索结果中提取标题
                        for key in ["search", "feed", "data"]:
                            if key in data:
                                items = data[key] if isinstance(data[key], list) else []
                                for item in items[:count]:
                                    title = item.get("title", "")
                                    if title and len(title) > 5:
                                        results.append({
                                            "title": title.strip(),
                                            "source": "toutiao",
                                        })
                except (json.JSONDecodeError, Exception):
                    pass

        return results[:count]

    def get_hot_topics(self, count: int = 20) -> list[dict]:
        """获取头条热搜榜"""
        results = []
        try:
            url = "https://www.toutiao.com/hot-event/hot-board/"
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("data", []):
                    title = item.get("Title", "")
                    if title:
                        results.append({
                            "title": title.strip(),
                            "source": "toutiao_hot",
                        })
        except Exception as e:
            print(f"  [WARN] 获取头条热搜失败: {e}")

        return results[:count]


# ==================== 搜狗微信搜索 ====================

class WeixinSearcher:
    """搜狗微信搜索"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.min_interval = 2.0
        self._last_request_time = 0

    def search(self, keyword: str, count: int = 10) -> list[dict]:
        """
        通过搜狗微信搜索相关文章标题
        返回 [{"title": str, "source": "weixin"}, ...]
        """
        results = []

        # 搜索文章（type=2）
        search_url = f"https://weixin.sogou.com/weixin?type=2&query={quote(keyword)}&ie=utf8"

        try:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed + random.uniform(0, 1))

            resp = self.session.get(search_url, timeout=20)
            self._last_request_time = time.time()

            if resp.status_code != 200:
                print(f"  [WARN] 搜狗搜索失败 (HTTP {resp.status_code})")
                return []

            if "antispider" in resp.url or "验证" in resp.text:
                print("  [WARN] 搜狗搜索触发反爬验证")
                return []

            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            # 搜索结果标题
            result_items = soup.select("div.txt-box h3 a")
            if not result_items:
                result_items = soup.select("ul.news-list h3 a")

            for link in result_items[:count]:
                title = link.get_text(strip=True)
                if title and len(title) > 5:
                    # 清理标题中的标签
                    title = re.sub(r"<[^>]+>", "", title)
                    results.append({
                        "title": title.strip(),
                        "source": "weixin",
                    })

        except Exception as e:
            print(f"  [WARN] 搜狗微信搜索异常: {e}")

        return results[:count]


# ==================== 统一搜索 + AI选题筛选 ====================

def search_hot_topics(keywords: list[str], sources: list[str] = None, count: int = 20) -> list[dict]:
    """
    根据关键词搜索热门选题
    返回 [{"title": str, "source": str}, ...]
    """
    if sources is None:
        sources = ["toutiao", "weixin"]

    all_results = []

    # 组合关键词搜索
    search_keyword = " ".join(keywords[:3])  # 最多用3个关键词

    if "toutiao" in sources:
        print(f"  [SEARCH] 头条搜索: {search_keyword}")
        toutiao = ToutiaoSearcher()
        results = toutiao.search(search_keyword, count=count)
        all_results.extend(results)
        # 也搜一下头条热搜
        if len(all_results) < count:
            hot = toutiao.get_hot_topics(count=10)
            # 用关键词过滤热搜
            for item in hot:
                if any(kw in item["title"] for kw in keywords):
                    all_results.append(item)

    if "weixin" in sources:
        print(f"  [SEARCH] 微信搜索: {search_keyword}")
        weixin = WeixinSearcher()
        results = weixin.search(search_keyword, count=count)
        all_results.extend(results)

    # 去重（按标题相似度）
    seen = set()
    unique = []
    for item in all_results:
        # 取标题前10个字作为去重键
        key = item["title"][:10]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:count]


def select_best_topic(
    track_name: str,
    track_prompt: str,
    hot_topics: list[dict],
) -> Optional[dict]:
    """
    用AI从热门选题中筛选出最适合当前赛道的选题
    返回 {"title": str, "angle": str} 或 None
    """
    if not hot_topics:
        print("  ⚠ 没有热门选题可供筛选")
        return None

    if not SILICONFLOW_API_KEY:
        # 没有API Key时，随机选一个
        topic = random.choice(hot_topics)
        return {"title": topic["title"], "angle": "直接切入"}

    from openai import OpenAI
    client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url=SILICONFLOW_BASE_URL)

    # 构建选题列表
    topic_list = "\n".join(
        f"{i+1}. {t['title']} (来源: {t.get('source', 'unknown')})"
        for i, t in enumerate(hot_topics[:15])
    )

    prompt = f"""你是一个微信公众号选题策划专家。

## 当前赛道
赛道名称：{track_name}
赛道定位：{track_prompt[:500]}

## 今日热门选题
{topic_list}

## 任务
从以上热门选题中，选出**最适合**该赛道的一篇选题，并给出写作切入角度。

选择标准：
1. 与赛道定位高度契合
2. 话题有热度、有共鸣
3. 能产出有深度的原创内容
4. 避免敏感话题

请以JSON格式输出：
```json
{{
    "selected_index": 数字,
    "title": "最终文章标题（不是原标题，是基于热点重新拟定的吸引人标题）",
    "angle": "写作切入角度（30字以内描述）",
    "reason": "选择理由（50字以内）"
}}
```

只输出JSON，不要其他内容。"""

    try:
        response = client.chat.completions.create(
            model="Qwen/Qwen3-8B",  # 选题筛选用小模型，速度快5-10倍
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500,
        )

        raw = response.choices[0].message.content.strip()
        # 提取JSON
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "title": data.get("title", ""),
                "angle": data.get("angle", ""),
                "reason": data.get("reason", ""),
                "original_topic": hot_topics[data.get("selected_index", 1) - 1]["title"] if data.get("selected_index", 0) <= len(hot_topics) else "",
            }
    except Exception as e:
        print(f"  [WARN] AI选题筛选失败: {e}")

    # 降级：随机选一个
    if hot_topics:
        topic = random.choice(hot_topics)
        return {"title": topic["title"], "angle": "直接切入"}

    return None


if __name__ == "__main__":
    # 测试
    print("=== 热门选题搜索测试 ===\n")

    # 测试头条搜索
    toutiao = ToutiaoSearcher()
    print("\n--- 头条热搜 ---")
    hot = toutiao.get_hot_topics(5)
    for h in hot:
        print(f"  {h['title']}")

    # 测试微信搜索
    print("\n--- 微信搜索: 情感 ---")
    weixin = WeixinSearcher()
    results = weixin.search("情感", count=5)
    for r in results:
        print(f"  {r['title']}")

    # 测试统一搜索
    print("\n--- 统一搜索: 情感赛道 ---")
    topics = search_hot_topics(["情感", "婚姻", "爱情"], sources=["weixin"], count=10)
    for t in topics:
        print(f"  [{t['source']}] {t['title']}")
