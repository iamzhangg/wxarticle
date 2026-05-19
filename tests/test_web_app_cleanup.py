import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import web_app  # noqa: E402


class CleanupGeneratingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.tempdir.name)
        self.original_output_dir = web_app.OUTPUT_DIR
        web_app.OUTPUT_DIR = self.temp_root / "output"

    def tearDown(self):
        web_app.OUTPUT_DIR = self.original_output_dir
        self.tempdir.cleanup()

    def _write_meta(self, article_dir: Path, *, status: str, generated_at: str):
        article_dir.mkdir(parents=True, exist_ok=True)
        (article_dir / "meta.json").write_text(
            json.dumps(
                {
                    "track": "AI赛道",
                    "status": status,
                    "generated_at": generated_at,
                    "title": "原始标题",
                    "summary": "原始摘要",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_cleanup_stale_generating_marks_old_placeholder_failed(self):
        article_dir = web_app.OUTPUT_DIR / "users" / "1" / "2026-05-14" / "AI赛道"
        old_time = (datetime.now() - timedelta(minutes=31)).isoformat()
        self._write_meta(article_dir, status="generating", generated_at=old_time)

        web_app._cleanup_stale_generating()

        meta = json.loads((article_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "failed")
        self.assertIn("服务重启导致生成中断", meta["summary"])

    def test_cleanup_keeps_recent_generating_untouched(self):
        article_dir = web_app.OUTPUT_DIR / "users" / "1" / "2026-05-14" / "AI赛道"
        recent_time = (datetime.now() - timedelta(minutes=5)).isoformat()
        self._write_meta(article_dir, status="generating", generated_at=recent_time)

        web_app._cleanup_stale_generating()

        meta = json.loads((article_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "generating")

    def test_cleanup_ignores_non_generating_status(self):
        article_dir = web_app.OUTPUT_DIR / "users" / "1" / "2026-05-14" / "AI赛道"
        old_time = (datetime.now() - timedelta(minutes=40)).isoformat()
        self._write_meta(article_dir, status="failed", generated_at=old_time)

        web_app._cleanup_stale_generating()

        meta = json.loads((article_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["title"], "原始标题")


if __name__ == "__main__":
    unittest.main()
