from __future__ import annotations
"""
wxarticle v2 - Web控制台

FastAPI后端，提供文章管理、下载、设置等API
前端为单页应用（SPA），内嵌在static/index.html中
"""
import json
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# 确保src目录在path中
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, PROJECT_ROOT
from data_sync import pull_data, push_data
from generation_service import (
    build_generation_env,
    classify_generation_failure,
    estimate_generation_timeout_seconds,
    mark_pending_dirs_failed,
    monitor_generation_process,
    prepare_pending_generation_dirs,
    read_log_tail,
    set_generation_progress_from_result,
    start_generation_subprocess,
)
from user_workspace import UserWorkspace
from web_routes import (
    create_admin_router,
    create_account_router,
    create_articles_router,
    create_auth_router,
    create_generation_router,
    create_settings_router,
)
from auth import get_user_api_key, get_user_pexels_api_key, init_auth_db, require_admin_user

app = FastAPI(title="wxarticle 控制台", version="2.0")

TEXT_MODEL_OPTIONS = [
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-R1",
]

IMAGE_MODEL_OPTIONS = [
    "Kwai-Kolors/Kolors",
]

IMAGE_SOURCE_OPTIONS = ["ai", "pexels"]

# 静态文件
STATIC_DIR = Path(__file__).parent / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# 生成任务状态
_generation_status_by_user: dict[int, dict] = {}
_generation_lock = threading.Lock()

# 定时任务状态
_scheduler_running = False


def _default_generation_status() -> dict:
    return {
        "running": False,
        "progress": "",
        "track_name": "",
        "results": [],
        "started_at": None,
        "finished_at": None,
    }


def _get_generation_status(user_id: int) -> dict:
    if user_id not in _generation_status_by_user:
        _generation_status_by_user[user_id] = _default_generation_status()
    return _generation_status_by_user[user_id]


def _user_workspace(user: dict) -> UserWorkspace:
    return UserWorkspace(
        project_root=PROJECT_ROOT,
        output_dir=OUTPUT_DIR,
        user=user,
        default_text_model=TEXT_MODEL_OPTIONS[0],
        default_image_model=IMAGE_MODEL_OPTIONS[0],
    )


def _user_output_dir(user: dict) -> Path:
    return _user_workspace(user).article_output_dir


def _user_config_path(user: dict) -> Path:
    return _user_workspace(user).config_path


def _load_user_config(user: dict) -> dict:
    return _user_workspace(user).load_config()


def _save_user_config(user: dict, config: dict) -> None:
    _user_workspace(user).save_config(config)


def _get_enabled_user_tracks(user: dict) -> list[dict]:
    return _user_workspace(user).get_enabled_tracks()


def _summarize_failure_message(message: str, limit: int = 120) -> str:
    """Compress multiline error output into a short summary for UI."""
    return classify_generation_failure(message, limit=limit)["summary"]


def _parse_generation_result(log_text: str) -> dict:
    """Parse the structured [RESULT] line written by src/main.py."""
    if not log_text:
        return {}
    matches = re.findall(r"^\[RESULT\]\s+(\{.*\})$", log_text, flags=re.MULTILINE)
    if not matches:
        return {}
    try:
        return json.loads(matches[-1])
    except Exception:
        return {}


def _estimate_generation_timeout_seconds(tracks: list[dict]) -> int:
    return estimate_generation_timeout_seconds(tracks)


def _read_log_tail(log_file: Path, lines: int = 60) -> str:
    return read_log_tail(log_file, lines=lines)


def _mark_pending_dirs_failed(
    pending_dirs: list[Path],
    failure_summary: str,
    failed_stage: str = "subprocess",
) -> None:
    mark_pending_dirs_failed(pending_dirs, failure_summary, failed_stage=failed_stage)


def _set_generation_progress_from_result(generation_status: dict, success: bool, result_payload: dict) -> None:
    set_generation_progress_from_result(generation_status, success, result_payload)


def _resolve_output_path(*parts: str) -> Path:
    """Resolve an article path and keep it inside OUTPUT_DIR."""
    base = OUTPUT_DIR.resolve()
    path = base.joinpath(*parts).resolve()
    if path != base and base not in path.parents:
        raise HTTPException(status_code=400, detail="非法路径")
    return path


def _resolve_user_output_path(user: dict, *parts: str) -> Path:
    return _user_workspace(user).resolve_output_path(*parts)


def _get_article_dir(user: dict, date: str, track_dir: str) -> Path:
    return _user_workspace(user).get_article_dir(date, track_dir)


def _get_next_user_output_dir(user: dict, date_str: str, track_name: str) -> Path:
    return _user_workspace(user).get_next_output_dir(date_str, track_name)


def _append_generation_history(user: dict, record: dict) -> None:
    _user_workspace(user).append_generation_history(record)


def _start_scheduler():
    """旧全局定时器已停用。

    公开部署下生成任务必须绑定 user_id，不能再由全局后台线程直接触发。
    后续需要定时生成时，应改成按用户读取各自配置并注入各自 API Key。
    """
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True
    print("[SCHEDULER] 全局定时器已停用：公开部署需按用户调度")


# 启动时拉取持久化数据 + 启动定时器
@app.on_event("startup")
async def startup_sync():
    init_auth_db()
    # pull_data 可能因网络问题卡住，放后台线程不阻塞启动
    import threading
    threading.Thread(target=pull_data, daemon=True).start()
    _cleanup_stale_generating()
    _start_scheduler()


def _cleanup_stale_generating():
    """清理残留的 'generating' 占位目录（服务重启后可能遗留）"""
    if not OUTPUT_DIR.exists():
        return
    now = datetime.now()
    cleaned = 0
    roots = []
    users_root = OUTPUT_DIR / "users"
    if users_root.exists():
        roots.extend([p for p in users_root.iterdir() if p.is_dir()])
    roots.append(OUTPUT_DIR)

    for output_root in roots:
        for date_dir in output_root.iterdir():
            if not date_dir.is_dir():
                continue
            for article_dir in date_dir.iterdir():
                if not article_dir.is_dir():
                    continue
                meta_path = article_dir / "meta.json"
                if not meta_path.exists():
                    continue
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("status") != "generating":
                        continue
                    # 超过30分钟的 generating 视为残留
                    gen_time = meta.get("generated_at", "")
                    if gen_time:
                        try:
                            gen_dt = datetime.fromisoformat(gen_time)
                            if (now - gen_dt).total_seconds() > 1800:
                                meta["status"] = "failed"
                                meta["title"] = f"生成失败：{meta.get('track', '未知')}赛道"
                                meta["summary"] = "服务重启导致生成中断，请重试"
                                with open(meta_path, "w", encoding="utf-8") as f:
                                    json.dump(meta, f, ensure_ascii=False, indent=2)
                                cleaned += 1
                        except Exception:
                            pass
                except Exception:
                    pass
    if cleaned:
        print(f"[CLEANUP] 清理了 {cleaned} 个残留的 generating 占位")


app.include_router(create_auth_router(_user_config_path))
app.include_router(create_account_router())
app.include_router(create_articles_router(_user_workspace))
app.include_router(
    create_settings_router(
        load_user_config=_load_user_config,
        save_user_config=_save_user_config,
        text_model_options=TEXT_MODEL_OPTIONS,
        image_model_options=IMAGE_MODEL_OPTIONS,
        image_source_options=IMAGE_SOURCE_OPTIONS,
    )
)
app.include_router(
    create_generation_router(
        user_workspace_factory=_user_workspace,
        get_generation_status_func=_get_generation_status,
        generation_lock=_generation_lock,
        get_user_api_key=get_user_api_key,
        get_user_pexels_api_key=get_user_pexels_api_key,
        estimate_generation_timeout_seconds=estimate_generation_timeout_seconds,
        prepare_pending_generation_dirs=prepare_pending_generation_dirs,
        build_generation_env=build_generation_env,
        start_generation_subprocess=start_generation_subprocess,
        mark_pending_dirs_failed=mark_pending_dirs_failed,
        monitor_generation_process=monitor_generation_process,
        parse_generation_result=_parse_generation_result,
        summarize_failure_message=_summarize_failure_message,
        push_data_callback=push_data,
        append_history_callback=_append_generation_history,
        project_root=PROJECT_ROOT,
        text_model_options=TEXT_MODEL_OPTIONS,
        image_model_options=IMAGE_MODEL_OPTIONS,
    )
)
app.include_router(create_admin_router(require_admin_user))


# ============ 前端页面 ============

@app.get("/", response_class=HTMLResponse)
def index():
    """返回前端SPA"""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h1>前端文件未找到</h1><p>请确保 src/web/static/index.html 存在</p>")


# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============ 启动入口 ============

def run_server(host: str = "127.0.0.1", port: int = 8080):
    """启动Web服务器"""
    import uvicorn
    print(f"[WEB] wxarticle 控制台启动: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="wxarticle Web控制台")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
