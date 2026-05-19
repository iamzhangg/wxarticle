import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import auth  # noqa: E402
import generation_service  # noqa: E402
import web_app  # noqa: E402


class FakeProcess:
    def __init__(self, retcode=1):
        self.retcode = retcode
        self.killed = False

    def poll(self):
        return self.retcode

    def kill(self):
        self.killed = True


class WebAppHelperTests(unittest.TestCase):
    def test_parse_generation_result_uses_last_result_line(self):
        log_text = "\n".join(
            [
                "[INFO] start",
                '[RESULT] {"status": "failed", "total_tasks": 2}',
                '[RESULT] {"status": "partial_success", "success_count": 1, "total_tasks": 2}',
            ]
        )

        result = web_app._parse_generation_result(log_text)

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["total_tasks"], 2)

    def test_summarize_failure_message_compacts_and_truncates(self):
        message = "error line 1\n\nline 2\tline 3"

        summary = web_app._summarize_failure_message(message, limit=18)

        self.assertEqual(summary, "error line 1 li...")

    def test_summarize_failure_message_classifies_api_key_errors(self):
        message = "requests.exceptions.HTTPError: 401 Unauthorized invalid api key"

        summary = web_app._summarize_failure_message(message)

        self.assertIn("API Key", summary)

    def test_read_log_tail_returns_last_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "generate.log"
            log_file.write_text("1\n2\n3\n4\n", encoding="utf-8")

            tail = web_app._read_log_tail(log_file, lines=2)

            self.assertEqual(tail, "3\n4\n")

    def test_mark_pending_dirs_failed_updates_meta(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "article"
            article_dir.mkdir(parents=True, exist_ok=True)
            meta_path = article_dir / "meta.json"
            meta_path.write_text(
                json.dumps({"track": "AI赛道", "status": "generating"}, ensure_ascii=False),
                encoding="utf-8",
            )

            web_app._mark_pending_dirs_failed([article_dir], "subprocess failed", failed_stage="subprocess")

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "failed")
            self.assertEqual(meta["failed_reason"], "subprocess failed")
            self.assertEqual(meta["failed_stage"], "subprocess")
            self.assertIn("生成失败", meta["title"])

    def test_mark_pending_dirs_failed_returns_failed_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            date_dir = Path(tmpdir) / "2026-05-14"
            article_dir = date_dir / "AI赛道"
            article_dir.mkdir(parents=True, exist_ok=True)
            meta_path = article_dir / "meta.json"
            meta_path.write_text(
                json.dumps({"track": "AI赛道", "status": "generating"}, ensure_ascii=False),
                encoding="utf-8",
            )

            results = generation_service.mark_pending_dirs_failed(
                [article_dir],
                "subprocess failed",
                failed_stage="subprocess",
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "failed")
            self.assertEqual(results[0]["article_id"], "2026-05-14/AI赛道")

    def test_mark_pending_dirs_failed_does_not_overwrite_finished_meta(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "article"
            article_dir.mkdir(parents=True, exist_ok=True)
            meta_path = article_dir / "meta.json"
            meta_path.write_text(
                json.dumps({"track": "AI赛道", "status": "done", "title": "已完成"}, ensure_ascii=False),
                encoding="utf-8",
            )

            web_app._mark_pending_dirs_failed([article_dir], "subprocess failed", failed_stage="subprocess")

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "done")
            self.assertEqual(meta["title"], "已完成")
            self.assertNotIn("failed_reason", meta)

    def test_set_generation_progress_from_result_handles_partial_success(self):
        status = web_app._default_generation_status()

        web_app._set_generation_progress_from_result(
            status,
            success=False,
            result_payload={"status": "partial_success", "success_count": 1, "total_tasks": 3},
        )

        self.assertEqual(status["progress"], "部分成功: 1/3")

    def test_prepare_pending_generation_dirs_creates_meta_placeholders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            shutil.copy2(ROOT / "config.yaml", temp_root / "config.yaml")
            workspace = web_app.UserWorkspace(
                project_root=temp_root,
                output_dir=temp_root / "output",
                user={"id": 7},
                default_text_model=web_app.TEXT_MODEL_OPTIONS[0],
                default_image_model=web_app.IMAGE_MODEL_OPTIONS[0],
            )

            pending_dirs, pre_assigned_dirs = generation_service.prepare_pending_generation_dirs(
                workspace,
                [{"name": "AI赛道", "articles_per_day": 2}],
            )

            self.assertEqual(len(pending_dirs), 2)
            self.assertEqual(len(pre_assigned_dirs["AI赛道"]), 2)
            meta = json.loads((pending_dirs[0] / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "generating")
            self.assertEqual(meta["articles_per_day"], 2)

    def test_build_generation_env_uses_user_workspace_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            shutil.copy2(ROOT / "config.yaml", temp_root / "config.yaml")
            workspace = web_app.UserWorkspace(
                project_root=temp_root,
                output_dir=temp_root / "output",
                user={"id": 9},
                default_text_model=web_app.TEXT_MODEL_OPTIONS[0],
                default_image_model=web_app.IMAGE_MODEL_OPTIONS[0],
            )

            env = generation_service.build_generation_env(
                workspace=workspace,
                generation_config={
                    "model": "deepseek-ai/DeepSeek-V3",
                    "image_model": "Kwai-Kolors/Kolors",
                    "image_source": "pexels",
                },
                api_key="siliconflow-test-key-1234567890",
                pexels_api_key="pexels-test-key-1234567890",
                pre_assigned_dirs={"AI赛道": ["C:/tmp/demo"]},
                default_text_model=web_app.TEXT_MODEL_OPTIONS[0],
                default_image_model=web_app.IMAGE_MODEL_OPTIONS[0],
            )

            self.assertEqual(env["WX_MODEL_NAME"], "deepseek-ai/DeepSeek-V3")
            self.assertEqual(env["IMAGE_SOURCE"], "pexels")
            self.assertEqual(env["WX_AI_API_KEY"], "siliconflow-test-key-1234567890")
            self.assertEqual(json.loads(env["WX_PRE_ASSIGNED_DIRS"]), {"AI赛道": ["C:/tmp/demo"]})

    def test_monitor_generation_records_failed_article_detail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            article_dir = temp_root / "2026-05-14" / "AI赛道"
            article_dir.mkdir(parents=True, exist_ok=True)
            (article_dir / "meta.json").write_text(
                json.dumps({"track": "AI赛道", "status": "generating"}, ensure_ascii=False),
                encoding="utf-8",
            )
            log_file = temp_root / "generate.log"
            log_file.write_text("401 Unauthorized invalid api key\n", encoding="utf-8")
            status = web_app._default_generation_status()
            status["started_at"] = "2026-05-14T09:00:00"
            appended = []

            generation_service.monitor_generation_process(
                proc=FakeProcess(retcode=1),
                generation_status=status,
                pending_dirs=[article_dir],
                log_file=log_file,
                parse_generation_result=lambda text: {},
                summarize_failure_message=web_app._summarize_failure_message,
                push_data_callback=lambda: None,
                append_history_callback=appended.append,
                lock=web_app._generation_lock,
            )

            self.assertEqual(len(appended), 1)
            self.assertEqual(appended[0]["failure_stage"], "api_key")
            self.assertEqual(appended[0]["results"][0]["status"], "failed")
            self.assertEqual(appended[0]["results"][0]["article_id"], "2026-05-14/AI赛道")

    def test_aihot_search_returns_hot_score_and_category(self):
        sample = [
            {
                "title": "Claude Design token limit doubled",
                "summary": "Anthropic announced token limits doubled for Claude Design.",
                "url": "https://x.com/claudeai/status/1",
                "source": "X：Claude (@claudeai)",
                "category": "ai-products",
                "publishedAt": "2026-05-19T00:00:00Z",
            },
            {
                "title": "Claude prompt cache diagnostics",
                "summary": "Prompt cache diagnostics are now in Claude Console.",
                "url": "https://x.com/claudeai/status/2",
                "source": "X：Claude (@claudeai)",
                "category": "tip",
                "publishedAt": "2026-05-19T00:00:00Z",
            },
        ]

        class FakeResp:
            status_code = 200

            def json(self):
                return {"items": sample}

        def fake_get(*args, **kwargs):
            return FakeResp()

        import topic_searcher

        original_get = topic_searcher.requests.get
        topic_searcher.requests.get = fake_get
        try:
            topics = topic_searcher.search_aihot_topics(count=2, generated_keys=set())
        finally:
            topic_searcher.requests.get = original_get

        self.assertEqual(len(topics), 2)
        self.assertIn("hot_score", topics[0])
        self.assertIn(topics[0]["category"], ("ai-products", "tip"))
        self.assertTrue(topics[0]["source"].startswith("aihot:"))


class WebAppApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.tempdir.name)
        shutil.copy2(ROOT / "config.yaml", self.temp_root / "config.yaml")

        auth.DATA_DIR = self.temp_root / "data"
        auth.DB_PATH = auth.DATA_DIR / "auth.db"
        auth.SECRET_PATH = auth.DATA_DIR / ".secret_key"

        web_app.PROJECT_ROOT = self.temp_root
        web_app.OUTPUT_DIR = self.temp_root / "output"
        web_app.pull_data = lambda: None
        web_app.push_data = lambda: None
        web_app._start_scheduler = lambda: None
        web_app._generation_status_by_user.clear()

        self.client_cm = TestClient(web_app.app)
        self.client = self.client_cm.__enter__()

    def tearDown(self):
        self.client_cm.__exit__(None, None, None)
        self.tempdir.cleanup()

    def _register(self, username="gio", password="passw0rd1"):
        response = self.client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["user"]

    def _logout(self):
        response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)

    def _seed_article(
        self,
        user_id: int,
        date: str,
        track_dir: str,
        *,
        title: str,
        summary: str = "",
        status: str = "done",
    ) -> Path:
        article_dir = self.temp_root / "output" / "users" / str(user_id) / date / track_dir
        article_dir.mkdir(parents=True, exist_ok=True)
        (article_dir / "article_content.html").write_text("<p>hello</p>", encoding="utf-8")
        (article_dir / "article.txt").write_text("hello", encoding="utf-8")
        (article_dir / "meta.json").write_text(
            json.dumps(
                {
                    "title": title,
                    "summary": summary,
                    "status": status,
                    "generated_at": f"{date}T09:30:00",
                    "word_count": 1234,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return article_dir

    def test_settings_requires_login(self):
        response = self.client.get("/api/settings")

        self.assertEqual(response.status_code, 401)

    def test_register_then_get_settings_returns_user_scoped_options(self):
        user = self._register()

        response = self.client.get("/api/settings")
        data = response.json()

        self.assertEqual(data["account"]["username"], user["username"])
        self.assertTrue(data["options"]["text_models"])
        self.assertEqual(data["generation"]["model"], web_app.TEXT_MODEL_OPTIONS[0])
        self.assertIn("tracks", data)

    def test_update_settings_rejects_invalid_text_model(self):
        self._register()

        response = self.client.put(
            "/api/settings",
            json={"generation": {"model": "not-allowed-model"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("生文模型不在允许列表中", response.text)

    def test_generate_requires_saved_siliconflow_api_key(self):
        self._register()

        response = self.client.post("/api/generate")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "error")
        self.assertIn("硅基流动 API Key", data["message"])

    def test_generate_blocks_pexels_without_pexels_key(self):
        self._register()
        save_key = self.client.put(
            "/api/account/api-key",
            json={"api_key": "sk-test-siliconflow-1234567890"},
        )
        self.assertEqual(save_key.status_code, 200)

        update_settings = self.client.put(
            "/api/settings",
            json={"generation": {"image_source": "pexels"}},
        )
        self.assertEqual(update_settings.status_code, 200)

        response = self.client.post("/api/generate")
        data = response.json()

        self.assertEqual(data["status"], "error")
        self.assertIn("Pexels API Key", data["message"])

    def test_list_articles_returns_only_current_user_articles(self):
        user1 = self._register("gio_a")
        self._seed_article(user1["id"], "2026-05-14", "AI赛道", title="用户A文章")
        self._logout()

        user2 = self._register("gio_b")
        self._seed_article(user2["id"], "2026-05-14", "AI赛道", title="用户B文章")

        response = self.client.get("/api/articles")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["articles"]), 1)
        self.assertEqual(data["articles"][0]["title"], "用户B文章")

    def test_article_detail_cannot_cross_user_boundary(self):
        user1 = self._register("gio_a")
        self._seed_article(user1["id"], "2026-05-14", "AI赛道", title="用户A文章")
        self._logout()

        self._register("gio_b")

        response = self.client.get("/api/articles/2026-05-14/AI赛道")

        self.assertEqual(response.status_code, 404)

    def test_generation_history_detail_route_is_not_shadowed_by_article_route(self):
        user = self._register()
        workspace = web_app._user_workspace(user)
        workspace.append_generation_history(
            {
                "id": "history-record-1",
                "status": "success",
                "track_name": "AI赛道",
                "total_tasks": 1,
                "success_count": 1,
                "failure_count": 0,
                "results": [
                    {
                        "track": "AI赛道",
                        "title": "历史文章",
                        "article_id": "2026-05-14/AI赛道",
                    }
                ],
            }
        )

        response = self.client.get("/api/articles/history/history-record-1")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["record"]["id"], "history-record-1")
        self.assertEqual(data["record"]["results"][0]["article_id"], "2026-05-14/AI赛道")


if __name__ == "__main__":
    unittest.main()
