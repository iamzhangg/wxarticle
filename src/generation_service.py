from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


FAILURE_PATTERNS = [
    ("api_key", ("api key", "apikey", "unauthorized", "401", "鉴权", "认证", "硅基流动 API Key"), "API Key 无效或未配置，请检查设置里的密钥"),
    ("rate_limit", ("rate limit", "429", "too many requests", "限流", "频率"), "API 请求被限流，请稍后重试"),
    ("network", ("timeout", "timed out", "connection", "proxy", "dns", "连接", "超时", "网络"), "网络连接或代理异常，请稍后重试"),
    ("article_generation", ("文章生成失败", "generate_article", "chat/completions", "模型响应", "response"), "文章生成阶段失败，请检查模型响应或重试"),
    ("image_generation", ("images/generations", "generate_cover", "generate_inline", "封面图", "插图", "图片"), "配图阶段异常，文章可能已生成但图片未完成"),
    ("formatter", ("排版失败", "markdown_to_platform_html", "formatter", "BeautifulSoup"), "排版阶段失败，请检查 Markdown 或 HTML 处理"),
    ("startup", ("启动子进程失败", "Popen", "No such file", "找不到"), "生成子进程启动失败，请检查运行环境"),
]


def estimate_generation_timeout_seconds(tracks: list[dict]) -> int:
    total_articles = sum(max(1, int(track.get("articles_per_day", 1) or 1)) for track in tracks)
    base_seconds = 180
    per_article_seconds = 720
    timeout_seconds = base_seconds + total_articles * per_article_seconds
    return max(600, min(timeout_seconds, 3600))


def read_log_tail(log_file: Path, lines: int = 60) -> str:
    if not log_file.exists():
        return ""
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except Exception:
        return ""


def compact_message(message: str, limit: int = 120) -> str:
    if not message:
        return ""
    compact = re.sub(r"\s+", " ", str(message)).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def classify_generation_failure(message: str, limit: int = 120) -> dict:
    compact = compact_message(message, limit=limit)
    lowered = compact.lower()
    for stage, keywords, summary in FAILURE_PATTERNS:
        if any(keyword.lower() in lowered for keyword in keywords):
            return {
                "stage": stage,
                "summary": compact_message(summary, limit=limit),
                "detail": compact,
            }
    return {
        "stage": "subprocess",
        "summary": compact or "文章生成失败，请重试",
        "detail": compact,
    }


def build_article_result_from_dir(output_dir: Path) -> dict | None:
    meta_path = output_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None

    article_id = f"{output_dir.parent.name}/{output_dir.name}" if output_dir.parent.name else output_dir.name
    return {
        "track": meta.get("track", ""),
        "title": meta.get("title", output_dir.name),
        "summary": meta.get("summary", ""),
        "status": meta.get("status", "done"),
        "failed_reason": meta.get("failed_reason", ""),
        "failed_stage": meta.get("failed_stage", ""),
        "output_dir": str(output_dir),
        "article_id": article_id,
    }


def mark_pending_dirs_failed(
    pending_dirs: list[Path],
    failure_summary: str,
    failed_stage: str = "subprocess",
) -> list[dict]:
    failed_results = []
    for output_dir in pending_dirs:
        meta_path = output_dir / "meta.json"
        if not meta_path.exists():
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("status") != "generating":
                continue
            meta["status"] = "failed"
            meta["title"] = f"生成失败：{meta.get('track', '未知')}赛道"
            meta["summary"] = failure_summary
            meta["failed_reason"] = failure_summary
            meta["failed_stage"] = meta.get("failed_stage") or failed_stage
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            result = build_article_result_from_dir(output_dir)
            if result:
                failed_results.append(result)
        except Exception:
            pass
    return failed_results


def set_generation_progress_from_result(generation_status: dict, success: bool, result_payload: dict) -> None:
    if success:
        generation_status["progress"] = "完成"
        if result_payload.get("results"):
            generation_status["results"] = result_payload.get("results", [])
        return
    if result_payload.get("status") == "partial_success":
        generation_status["progress"] = (
            f"部分成功: {result_payload.get('success_count', 0)}/"
            f"{result_payload.get('total_tasks', 0)}"
        )
        generation_status["results"] = result_payload.get("results", [])
        return
    generation_status["progress"] = "生成失败"


def prepare_pending_generation_dirs(
    workspace,
    tracks: list[dict],
    now: datetime | None = None,
) -> tuple[list[Path], dict[str, list[str]]]:
    now = now or datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    pending_dirs: list[Path] = []
    pre_assigned_dirs: dict[str, list[str]] = {}

    for track in tracks:
        article_count = max(1, int(track.get("articles_per_day", 1) or 1))
        pre_assigned_dirs[track["name"]] = []
        for index in range(article_count):
            out_dir = workspace.get_next_output_dir(date_str, track["name"])
            out_dir.mkdir(parents=True, exist_ok=True)
            meta = {
                "track": track["name"],
                "title": f"正在生成：{track['name']}文章...",
                "summary": "文章正在生成中，请稍候",
                "word_count": 0,
                "generated_at": now.isoformat(),
                "status": "generating",
                "article_index": index + 1,
                "articles_per_day": article_count,
                "failed_reason": "",
                "failed_stage": "",
            }
            with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            pending_dirs.append(out_dir)
            pre_assigned_dirs[track["name"]].append(str(out_dir))

    return pending_dirs, pre_assigned_dirs


def build_generation_env(
    workspace,
    generation_config: dict,
    api_key: str,
    pexels_api_key: str,
    pre_assigned_dirs: dict[str, list[str]],
    default_text_model: str,
    default_image_model: str,
) -> dict[str, str]:
    env = os.environ.copy()
    for proxy_key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        env.pop(proxy_key, None)

    env["WX_PRE_ASSIGNED_DIRS"] = json.dumps(pre_assigned_dirs, ensure_ascii=True)
    env["WX_OUTPUT_DIR"] = str(workspace.article_output_dir)
    env["WX_CONFIG_PATH"] = str(workspace.config_path)
    env["WX_AI_API_KEY"] = api_key
    env["WX_PEXELS_API_KEY"] = pexels_api_key
    env["WX_MODEL_NAME"] = generation_config.get("model", default_text_model)
    env["WX_IMAGE_MODEL_NAME"] = generation_config.get("image_model", default_image_model)
    env["IMAGE_SOURCE"] = generation_config.get("image_source", "ai")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def start_generation_subprocess(
    project_root: Path,
    log_file: Path,
    env: dict[str, str],
    track_name: str = "",
):
    cmd = [sys.executable, str(project_root / "src" / "main.py")]
    if track_name:
        cmd.extend(["--track", track_name])

    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    log_fh = open(str(log_file), "wb")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
    finally:
        log_fh.close()

    return proc


def monitor_generation_process(
    *,
    proc,
    generation_status: dict,
    pending_dirs: list[Path],
    log_file: Path,
    parse_generation_result,
    summarize_failure_message,
    push_data_callback,
    append_history_callback,
    lock,
) -> None:
    with lock:
        generation_status["progress"] = "正在生成..."

    success = False
    retcode = None
    result_payload = {}
    timeout_seconds = int(generation_status.get("timeout_seconds") or 600)
    timeout_message = f"超时（{timeout_seconds // 60}分钟）"

    try:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            retcode = proc.poll()
            if retcode is not None:
                success = retcode == 0
                break
            time.sleep(2)
        else:
            proc.kill()
            with lock:
                generation_status["progress"] = f"错误: {timeout_message}"
        if retcode is not None:
            result_payload = parse_generation_result(read_log_tail(log_file, lines=200))
            with lock:
                set_generation_progress_from_result(generation_status, success, result_payload)
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        with lock:
            generation_status["progress"] = f"错误: {e}"
    finally:
        failure_summary = ""
        final_status = "failed"
        if retcode is not None and result_payload.get("status") == "partial_success":
            generation_status["results"] = result_payload.get("results", [])
            final_status = "partial_success"
        elif success:
            final_status = "success"
            if result_payload.get("results"):
                generation_status["results"] = result_payload.get("results", [])
        failure_detail = {}
        failed_results = []
        if not success:
            log_excerpt = read_log_tail(log_file)
            failure_detail = classify_generation_failure(
                log_excerpt or generation_status.get("progress", "")
            )
            failure_summary = failure_detail["summary"]
            failed_results = mark_pending_dirs_failed(
                pending_dirs,
                failure_summary,
                failed_stage=failure_detail["stage"],
            )
        history_results = []
        for item in generation_status.get("results", []):
            item = dict(item)
            output_dir = str(item.get("output_dir") or "")
            item["output_dir"] = output_dir
            if output_dir:
                path = Path(output_dir)
                item["article_id"] = f"{path.parent.name}/{path.name}" if path.parent.name else path.name
            history_results.append(item)
        if not history_results and result_payload.get("results"):
            for item in result_payload.get("results", []):
                item = dict(item)
                output_dir = str(item.get("output_dir") or "")
                item["output_dir"] = output_dir
                if output_dir:
                    path = Path(output_dir)
                    item["article_id"] = f"{path.parent.name}/{path.name}" if path.parent.name else path.name
                history_results.append(item)
        existing_article_ids = {item.get("article_id") for item in history_results}
        for item in failed_results:
            if item.get("article_id") not in existing_article_ids:
                history_results.append(item)
        total_tasks = result_payload.get("total_tasks", len(pending_dirs))
        success_count = result_payload.get(
            "success_count",
            len([item for item in history_results if item.get("status") != "failed"]) if success else 0,
        )
        failure_count = result_payload.get(
            "failure_count",
            max(total_tasks - success_count, 0),
        )
        with lock:
            generation_status["running"] = False
            generation_status["finished_at"] = datetime.now().isoformat()
            if not success and generation_status["progress"] == "生成失败":
                generation_status["progress"] = f"生成失败: {failure_summary}"
        if append_history_callback:
            try:
                append_history_callback(
                    {
                        "id": generation_status.get("started_at") or datetime.now().isoformat(),
                        "started_at": generation_status.get("started_at"),
                        "finished_at": generation_status.get("finished_at"),
                        "track_name": generation_status.get("track_name", ""),
                        "status": final_status,
                        "progress": generation_status.get("progress", ""),
                        "results": history_results,
                        "total_tasks": total_tasks,
                        "success_count": success_count,
                        "failure_count": failure_count,
                        "failure_summary": failure_summary,
                        "failure_stage": failure_detail.get("stage", ""),
                        "failure_detail": failure_detail.get("detail", ""),
                        "log_excerpt": read_log_tail(log_file, lines=80),
                    }
                )
            except Exception:
                pass
        threading.Thread(target=push_data_callback, daemon=True).start()
