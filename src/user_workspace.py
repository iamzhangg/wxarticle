from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException


@dataclass
class UserWorkspace:
    project_root: Path
    output_dir: Path
    user: dict
    default_text_model: str
    default_image_model: str

    @property
    def root(self) -> Path:
        return self.project_root / "data" / "users" / str(self.user["id"])

    @property
    def article_output_dir(self) -> Path:
        path = self.output_dir / "users" / str(self.user["id"])
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def config_path(self) -> Path:
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        path = root / "config.yaml"
        if not path.exists():
            shutil.copy2(self.project_root / "config.yaml", path)
        return path

    @property
    def trash_dir(self) -> Path:
        path = self.article_output_dir / "_trash"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def generation_history_path(self) -> Path:
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        return root / "generation_history.json"

    def load_config(self) -> dict:
        import yaml

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        generation = config.setdefault("generation", {})
        generation.setdefault("model", self.default_text_model)
        generation.setdefault("image_source", "ai")
        generation.setdefault("image_model", self.default_image_model)
        return config

    def save_config(self, config: dict) -> None:
        import yaml

        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def get_enabled_tracks(self) -> list[dict]:
        config = self.load_config()
        return [track for track in config.get("tracks", []) if track.get("enabled", True)]

    def resolve_output_path(self, *parts: str) -> Path:
        base = self.article_output_dir.resolve()
        path = base.joinpath(*parts).resolve()
        if path != base and base not in path.parents:
            raise HTTPException(status_code=400, detail="非法路径")
        return path

    def get_article_dir(self, date: str, track_dir: str) -> Path:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise HTTPException(status_code=400, detail="日期格式错误")
        if any(sep in track_dir for sep in ("/", "\\")) or track_dir in ("", ".", ".."):
            raise HTTPException(status_code=400, detail="文章目录名错误")
        return self.resolve_output_path(date, track_dir)

    def get_next_output_dir(self, date_str: str, track_name: str) -> Path:
        date_dir = self.article_output_dir / date_str
        if not date_dir.exists():
            return date_dir / track_name
        if not (date_dir / track_name).exists():
            return date_dir / track_name
        seq = 2
        while (date_dir / f"{track_name}_{seq}").exists():
            seq += 1
        return date_dir / f"{track_name}_{seq}"

    def list_articles(self) -> list[dict]:
        if not self.article_output_dir.exists():
            return []

        articles = []
        for date_dir in sorted(self.article_output_dir.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_dir.name):
                continue
            for article_dir in sorted(date_dir.iterdir(), reverse=True):
                if not article_dir.is_dir():
                    continue
                articles.append(self._build_article_info(date_dir.name, article_dir))

        articles.sort(key=lambda article: article.get("generated_at") or article["date"], reverse=True)
        return articles

    def list_trash_articles(self) -> list[dict]:
        if not self.trash_dir.exists():
            return []

        articles = []
        for date_dir in sorted(self.trash_dir.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            for article_dir in sorted(date_dir.iterdir(), reverse=True):
                if not article_dir.is_dir():
                    continue
                article = self._build_article_info(date_dir.name, article_dir)
                article["status"] = "trash"
                article["id"] = f"trash/{date_dir.name}/{article_dir.name}"
                article["is_trash"] = True
                articles.append(article)

        articles.sort(key=lambda article: article.get("generated_at") or article["date"], reverse=True)
        return articles

    def get_article_detail(self, date: str, track_dir: str) -> dict:
        article_dir = self.get_article_dir(date, track_dir)
        if not article_dir.exists():
            raise HTTPException(status_code=404, detail="文章不存在")

        result = {
            "date": date,
            "track_dir": track_dir,
            "files": [],
        }

        meta_path = article_dir / "meta.json"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                result["meta"] = json.load(f)

        for file_path in sorted(article_dir.iterdir()):
            if file_path.is_file():
                result["files"].append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "type": file_path.suffix.lstrip("."),
                })

        html_path = article_dir / "article_content.html"
        if html_path.exists():
            with open(html_path, "r", encoding="utf-8") as f:
                result["html_content"] = f.read()

        txt_path = article_dir / "article.txt"
        if txt_path.exists():
            with open(txt_path, "r", encoding="utf-8") as f:
                result["text_content"] = f.read()

        return result

    def move_article_to_trash(self, date: str, track_dir: str) -> Path:
        article_dir = self.get_article_dir(date, track_dir)
        if not article_dir.exists():
            raise HTTPException(status_code=404, detail="文章不存在")

        trash_date_dir = self.trash_dir / date
        trash_date_dir.mkdir(parents=True, exist_ok=True)

        destination = trash_date_dir / track_dir
        if destination.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            destination = trash_date_dir / f"{track_dir}_{timestamp}"

        shutil.move(str(article_dir), str(destination))
        return destination

    def load_generation_history(self) -> list[dict]:
        path = self.generation_history_path
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def append_generation_history(self, record: dict) -> None:
        history = self.load_generation_history()
        history.insert(0, record)
        history = history[:50]
        with open(self.generation_history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def restore_article_from_trash(self, date: str, track_dir: str) -> Path:
        trash_article_dir = self.trash_dir / date / track_dir
        if not trash_article_dir.exists():
            raise HTTPException(status_code=404, detail="回收站文章不存在")

        restore_date_dir = self.article_output_dir / date
        restore_date_dir.mkdir(parents=True, exist_ok=True)

        destination = restore_date_dir / track_dir
        if destination.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            destination = restore_date_dir / f"{track_dir}_{timestamp}"

        shutil.move(str(trash_article_dir), str(destination))
        return destination

    def _build_article_info(self, date_str: str, article_dir: Path) -> dict:
        meta_path = article_dir / "meta.json"
        cover_path = article_dir / "cover.jpg"
        html_path = article_dir / "article_content.html"

        track_name, seq = self._parse_track_dir_name(article_dir.name)
        article_info = {
            "id": f"{date_str}/{article_dir.name}",
            "date": date_str,
            "track": track_name,
            "seq": seq,
            "has_cover": cover_path.exists(),
            "has_html": html_path.exists(),
            "title": article_dir.name,
            "summary": "",
            "word_count": 0,
            "generated_at": "",
            "topic_reason": "",
            "topic_source": "",
            "status": "done",
            "failed_reason": "",
            "failed_stage": "",
        }

        if not meta_path.exists():
            return article_info

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        article_info.update({
            "title": meta.get("title", article_dir.name),
            "summary": meta.get("summary", ""),
            "word_count": meta.get("word_count", 0),
            "generated_at": meta.get("generated_at", ""),
            "failed_reason": meta.get("failed_reason", ""),
            "failed_stage": meta.get("failed_stage", ""),
        })
        if meta.get("status") == "generating":
            article_info["status"] = "generating"
        elif meta.get("status") == "failed":
            article_info["status"] = "failed"

        hot_topic = meta.get("hot_topic", {})
        if hot_topic:
            article_info["topic_reason"] = self._format_topic_reason(hot_topic)
            article_info["topic_source"] = hot_topic.get("original_topic", "")

        return article_info

    @staticmethod
    def _parse_track_dir_name(dir_name: str) -> tuple[str, int]:
        if "_" in dir_name and dir_name.rsplit("_", 1)[-1].isdigit():
            track_name, seq = dir_name.rsplit("_", 1)
            return track_name, int(seq)
        return dir_name, 0

    @staticmethod
    def _format_topic_reason(hot_topic: dict) -> str:
        parts = []
        original = hot_topic.get("original_topic", "")
        reason = hot_topic.get("reason", "")
        angle = hot_topic.get("angle", "")
        if original:
            parts.append(f"热点：{original}")
        if reason:
            parts.append(reason)
        if angle and angle != "直接切入":
            parts.append(f"角度：{angle}")
        return " | ".join(parts)
