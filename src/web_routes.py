from __future__ import annotations

import re
from datetime import datetime
import threading

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse

from auth import (
    authenticate_user,
    clear_session,
    create_session,
    create_user,
    get_current_user,
    save_user_api_key,
    save_user_pexels_api_key,
)


def _validate_articles_per_day(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="每日篇数必须是整数")
    if parsed < 1 or parsed > 5:
        raise HTTPException(status_code=400, detail="每日篇数必须在 1 到 5 之间")
    return parsed


def _validate_word_count(value, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field_name}必须是整数")
    if parsed < 500 or parsed > 8000:
        raise HTTPException(status_code=400, detail=f"{field_name}必须在 500 到 8000 之间")
    return parsed


def _validate_schedule_time(value) -> str:
    time_str = str(value or "").strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_str):
        raise HTTPException(status_code=400, detail="定时生成时间格式必须是 HH:MM")
    return time_str


def create_auth_router(user_config_path_func):
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/register")
    def register(payload: dict, response: Response):
        user = create_user(str(payload.get("username", "")), str(payload.get("password", "")))
        create_session(response, user["id"])
        user_config_path_func(user)
        return {"user": user}

    @router.post("/login")
    def login(payload: dict, response: Response):
        user = authenticate_user(str(payload.get("username", "")), str(payload.get("password", "")))
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        create_session(response, user["id"])
        return {"user": user}

    @router.post("/logout")
    def logout(response: Response, wx_session: str = Cookie(default="")):
        clear_session(response, wx_session)
        return {"status": "ok"}

    @router.get("/me")
    def auth_me(user: dict = Depends(get_current_user)):
        return {"user": user}

    return router


def create_account_router():
    router = APIRouter(prefix="/api/account", tags=["account"])

    @router.put("/api-key")
    def update_api_key(payload: dict, user: dict = Depends(get_current_user)):
        save_user_api_key(user["id"], str(payload.get("api_key", "")))
        return {"status": "ok", "message": "硅基流动 API Key 已保存"}

    @router.put("/pexels-api-key")
    def update_pexels_api_key(payload: dict, user: dict = Depends(get_current_user)):
        save_user_pexels_api_key(user["id"], str(payload.get("api_key", "")))
        return {"status": "ok", "message": "Pexels API Key 已保存"}

    return router


def create_articles_router(user_workspace_factory):
    router = APIRouter(prefix="/api/articles", tags=["articles"])

    @router.get("")
    def list_articles(user: dict = Depends(get_current_user)):
        return {"articles": user_workspace_factory(user).list_articles()}

    @router.get("/trash")
    def list_trash_articles(user: dict = Depends(get_current_user)):
        return {"articles": user_workspace_factory(user).list_trash_articles()}

    @router.get("/history")
    def list_generation_history(user: dict = Depends(get_current_user)):
        workspace = user_workspace_factory(user)
        return {"history": workspace.load_generation_history()}

    @router.get("/history/{record_id}")
    def get_generation_history_item(record_id: str, user: dict = Depends(get_current_user)):
        history = user_workspace_factory(user).load_generation_history()
        for item in history:
            if str(item.get("id")) == record_id:
                return {"record": item}
        raise HTTPException(status_code=404, detail="记录不存在")

    @router.get("/{date}/{track_dir}")
    def get_article_detail(date: str, track_dir: str, user: dict = Depends(get_current_user)):
        return user_workspace_factory(user).get_article_detail(date, track_dir)

    @router.get("/{date}/{track_dir}/cover")
    def download_cover(date: str, track_dir: str, user: dict = Depends(get_current_user)):
        cover_path = user_workspace_factory(user).get_article_dir(date, track_dir) / "cover.jpg"
        if not cover_path.exists():
            raise HTTPException(status_code=404, detail="封面图不存在")
        return FileResponse(
            cover_path,
            media_type="image/jpeg",
            filename=f"{track_dir}_cover.jpg",
        )

    @router.get("/{date}/{track_dir}/html")
    def download_html(date: str, track_dir: str, user: dict = Depends(get_current_user)):
        html_path = user_workspace_factory(user).get_article_dir(date, track_dir) / "article_content.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="HTML文件不存在")
        return FileResponse(
            html_path,
            media_type="text/html",
            filename=f"{track_dir}_article.html",
        )

    @router.get("/{date}/{track_dir}/preview")
    def preview_article(date: str, track_dir: str, user: dict = Depends(get_current_user)):
        article_dir = user_workspace_factory(user).get_article_dir(date, track_dir)
        html_path = article_dir / "article.html"
        if not html_path.exists():
            html_path = article_dir / "article_content.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="预览页面不存在")

        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)

    @router.delete("/{date}/{track_dir}")
    def delete_article(date: str, track_dir: str, user: dict = Depends(get_current_user)):
        workspace = user_workspace_factory(user)
        destination = workspace.move_article_to_trash(date, track_dir)
        return {
            "status": "ok",
            "message": f"已移到回收站 {date}/{track_dir}",
            "trash_path": str(destination),
        }

    @router.post("/trash/{date}/{track_dir}/restore")
    def restore_article(date: str, track_dir: str, user: dict = Depends(get_current_user)):
        workspace = user_workspace_factory(user)
        destination = workspace.restore_article_from_trash(date, track_dir)
        return {
            "status": "ok",
            "message": f"已从回收站恢复 {date}/{track_dir}",
            "restore_path": str(destination),
        }

    @router.delete("/trash/{date}/{track_dir}")
    def purge_article(date: str, track_dir: str, user: dict = Depends(get_current_user)):
        workspace = user_workspace_factory(user)
        trash_article_dir = workspace.trash_dir / date / track_dir
        if not trash_article_dir.exists():
            raise HTTPException(status_code=404, detail="回收站文章不存在")
        import shutil
        shutil.rmtree(trash_article_dir)
        return {"status": "ok", "message": f"已彻底删除 {date}/{track_dir}"}

    return router


def create_settings_router(
    *,
    load_user_config,
    save_user_config,
    text_model_options: list[str],
    image_model_options: list[str],
    image_source_options: list[str],
):
    router = APIRouter(prefix="/api/settings", tags=["settings"])

    @router.get("")
    def get_settings(user: dict = Depends(get_current_user)):
        config = load_user_config(user)

        settings = {
            "tracks": [],
            "generation": config.get("generation", {}),
            "schedule": config.get("schedule", {}),
            "account": {
                "username": user["username"],
                "role": user["role"],
                "has_api_key": user["has_api_key"],
                "has_pexels_api_key": user.get("has_pexels_api_key", False),
            },
            "options": {
                "text_models": text_model_options,
                "image_models": image_model_options,
                "image_sources": image_source_options,
            },
        }

        for track in config.get("tracks", []):
            settings["tracks"].append({
                "name": track["name"],
                "enabled": track.get("enabled", True),
                "keywords": track.get("keywords", []),
                "articles_per_day": track.get("articles_per_day", 1),
            })

        return settings

    @router.put("")
    def update_settings(settings: dict, user: dict = Depends(get_current_user)):
        config = load_user_config(user)

        if "tracks" in settings:
            for track_update in settings["tracks"]:
                track_name = str(track_update.get("name", ""))
                for track in config.get("tracks", []):
                    if track["name"] == track_name:
                        if "enabled" in track_update:
                            track["enabled"] = track_update["enabled"]
                        if "articles_per_day" in track_update:
                            track["articles_per_day"] = _validate_articles_per_day(track_update["articles_per_day"])

        if "generation" in settings:
            generation_update = dict(settings["generation"])
            model = generation_update.get("model")
            if model and model not in text_model_options:
                raise HTTPException(status_code=400, detail="生文模型不在允许列表中")
            image_source = generation_update.get("image_source")
            if image_source and image_source not in image_source_options:
                raise HTTPException(status_code=400, detail="图片来源配置不正确")
            image_model = generation_update.get("image_model")
            if image_model and image_model not in image_model_options:
                raise HTTPException(status_code=400, detail="图片模型不在允许列表中")
            if "word_count_min" in generation_update:
                generation_update["word_count_min"] = _validate_word_count(generation_update["word_count_min"], "最小字数")
            if "word_count_max" in generation_update:
                generation_update["word_count_max"] = _validate_word_count(generation_update["word_count_max"], "最大字数")
            word_min = generation_update.get("word_count_min", config.get("generation", {}).get("word_count_min", 1200))
            word_max = generation_update.get("word_count_max", config.get("generation", {}).get("word_count_max", 1300))
            if int(word_min) > int(word_max):
                raise HTTPException(status_code=400, detail="最小字数不能大于最大字数")
            config["generation"].update(generation_update)

        if "schedule" in settings:
            schedule_update = dict(settings["schedule"])
            if "time" in schedule_update:
                schedule_update["time"] = _validate_schedule_time(schedule_update["time"])
            config["schedule"].update(schedule_update)

        save_user_config(user, config)
        return {"status": "ok", "message": "设置已保存"}

    return router


def create_generation_router(
    *,
    user_workspace_factory,
    get_generation_status_func,
    generation_lock,
    get_user_api_key,
    get_user_pexels_api_key,
    estimate_generation_timeout_seconds,
    prepare_pending_generation_dirs,
    build_generation_env,
    start_generation_subprocess,
    mark_pending_dirs_failed,
    monitor_generation_process,
    parse_generation_result,
    summarize_failure_message,
    push_data_callback,
    append_history_callback,
    project_root,
    text_model_options: list[str],
    image_model_options: list[str],
):
    router = APIRouter(prefix="/api", tags=["generation"])

    @router.post("/generate")
    def trigger_generate(track_name: str = "", user: dict = Depends(get_current_user)):
        workspace = user_workspace_factory(user)
        with generation_lock:
            generation_status = get_generation_status_func(user["id"])
            if generation_status["running"]:
                return {"status": "already_running", "message": "已有生成任务在运行中"}

            api_key = get_user_api_key(user["id"])
            if not api_key:
                return {"status": "error", "message": "请先在设置里保存你的硅基流动 API Key"}
            generation_config = workspace.load_config().get("generation", {})
            image_source = generation_config.get("image_source", "ai")
            pexels_api_key = get_user_pexels_api_key(user["id"])
            if image_source == "pexels" and not pexels_api_key:
                return {"status": "error", "message": "当前图片来源是 Pexels，请先保存你的 Pexels API Key"}

            tracks = workspace.get_enabled_tracks()
            if track_name:
                tracks = [track for track in tracks if track["name"] == track_name]
                if not tracks:
                    return {"status": "error", "message": f"赛道 '{track_name}' 不存在或未启用"}

            if not tracks:
                return {"status": "error", "message": "没有启用的赛道，请检查 config.yaml"}

            generation_status.update({
                "running": True,
                "progress": "准备生成...",
                "track_name": track_name,
                "results": [],
                "started_at": datetime.now().isoformat(),
                "finished_at": None,
                "timeout_seconds": estimate_generation_timeout_seconds(tracks),
            })

            try:
                pending_dirs, pre_assigned_dirs = prepare_pending_generation_dirs(workspace, tracks)
            except Exception as e:
                generation_status["running"] = False
                generation_status["progress"] = f"准备生成失败: {e}"
                generation_status["finished_at"] = datetime.now().isoformat()
                return {"status": "error", "message": f"准备生成失败: {e}"}

        log_file = project_root / "generate.log"
        env = build_generation_env(
            workspace=workspace,
            generation_config=generation_config,
            api_key=api_key,
            pexels_api_key=pexels_api_key,
            pre_assigned_dirs=pre_assigned_dirs,
            default_text_model=text_model_options[0],
            default_image_model=image_model_options[0],
        )
        try:
            proc = start_generation_subprocess(
                project_root=project_root,
                log_file=log_file,
                env=env,
                track_name=track_name,
            )
        except Exception as e:
            print(f"[GEN] 启动子进程失败: {e}")
            failure_detail = summarize_failure_message(f"启动子进程失败: {e}")
            mark_pending_dirs_failed(pending_dirs, failure_detail, failed_stage="startup")
            with generation_lock:
                generation_status["running"] = False
                generation_status["progress"] = f"启动子进程失败: {failure_detail}"
                generation_status["finished_at"] = datetime.now().isoformat()
            return {"status": "error", "message": f"启动子进程失败: {failure_detail}"}

        track_names = [track["name"] for track in tracks]
        thread = threading.Thread(
            target=monitor_generation_process,
            kwargs={
                "proc": proc,
                "generation_status": generation_status,
                "pending_dirs": pending_dirs,
                "log_file": log_file,
                "parse_generation_result": parse_generation_result,
                "summarize_failure_message": summarize_failure_message,
                "push_data_callback": push_data_callback,
                "append_history_callback": append_history_callback,
                "lock": generation_lock,
            },
            daemon=True,
        )
        thread.start()

        return {"status": "started", "message": "生成任务已启动", "tracks": track_names}

    @router.get("/generate/status")
    def get_generation_status(user: dict = Depends(get_current_user)):
        return get_generation_status_func(user["id"])

    @router.get("/log")
    def get_generate_log():
        raise HTTPException(status_code=404, detail="接口已关闭")

    return router


def create_admin_router(require_admin_user):
    router = APIRouter(prefix="/api", tags=["admin"])

    @router.post("/update")
    def self_update(user: dict = Depends(get_current_user)):
        require_admin_user(user)
        raise HTTPException(status_code=404, detail="接口已关闭")

    @router.post("/restart")
    def restart_service(user: dict = Depends(get_current_user)):
        require_admin_user(user)
        raise HTTPException(status_code=404, detail="接口已关闭")

    return router
