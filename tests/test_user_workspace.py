import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from user_workspace import UserWorkspace  # noqa: E402


class UserWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.tempdir.name)
        shutil.copy2(ROOT / "config.yaml", self.temp_root / "config.yaml")
        self.workspace = UserWorkspace(
            project_root=self.temp_root,
            output_dir=self.temp_root / "output",
            user={"id": 42},
            default_text_model="Qwen/Qwen3-235B-A22B-Instruct-2507",
            default_image_model="Kwai-Kolors/Kolors",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def _seed_article(self, date: str, track_dir: str, *, title: str, status: str = "done") -> Path:
        article_dir = self.workspace.article_output_dir / date / track_dir
        article_dir.mkdir(parents=True, exist_ok=True)
        (article_dir / "article_content.html").write_text("<p>hello</p>", encoding="utf-8")
        (article_dir / "article.txt").write_text("hello", encoding="utf-8")
        (article_dir / "cover.jpg").write_bytes(b"jpg")
        (article_dir / "meta.json").write_text(
            json.dumps(
                {
                    "title": title,
                    "summary": f"{title}摘要",
                    "status": status,
                    "generated_at": f"{date}T10:00:00",
                    "word_count": 888,
                    "hot_topic": {
                        "original_topic": "原始热点",
                        "reason": "值得写",
                        "angle": "实战拆解",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return article_dir

    def test_resolve_output_path_rejects_escape(self):
        with self.assertRaises(HTTPException) as ctx:
            self.workspace.resolve_output_path("..", "outside")

        self.assertEqual(ctx.exception.status_code, 400)

    def test_get_article_dir_validates_date_and_track_dir(self):
        with self.assertRaises(HTTPException):
            self.workspace.get_article_dir("20260514", "AI赛道")
        with self.assertRaises(HTTPException):
            self.workspace.get_article_dir("2026-05-14", "../AI赛道")

    def test_get_next_output_dir_increments_suffix(self):
        first_dir = self.workspace.get_next_output_dir("2026-05-14", "AI赛道")
        first_dir.mkdir(parents=True, exist_ok=True)
        second_dir = self.workspace.get_next_output_dir("2026-05-14", "AI赛道")

        self.assertEqual(first_dir.name, "AI赛道")
        self.assertEqual(second_dir.name, "AI赛道_2")

    def test_list_articles_sorts_and_formats_topic_reason(self):
        self._seed_article("2026-05-13", "AI赛道", title="较早文章")
        self._seed_article("2026-05-14", "AI赛道_2", title="较新文章", status="failed")

        articles = self.workspace.list_articles()

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0]["title"], "较新文章")
        self.assertEqual(articles[0]["track"], "AI赛道")
        self.assertEqual(articles[0]["seq"], 2)
        self.assertEqual(articles[0]["status"], "failed")
        self.assertIn("热点：原始热点", articles[0]["topic_reason"])
        self.assertIn("角度：实战拆解", articles[0]["topic_reason"])

    def test_get_article_detail_returns_files_and_content(self):
        self._seed_article("2026-05-14", "AI赛道", title="详情文章")

        detail = self.workspace.get_article_detail("2026-05-14", "AI赛道")

        self.assertEqual(detail["meta"]["title"], "详情文章")
        self.assertIn("html_content", detail)
        self.assertIn("text_content", detail)
        self.assertTrue(any(file["name"] == "article_content.html" for file in detail["files"]))


if __name__ == "__main__":
    unittest.main()
