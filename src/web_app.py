from __future__ import annotations
"""
wxarticle v2 - Web控制台

FastAPI后端，提供文章管理、下载、设置等API
前端为单页应用（SPA），内嵌在static/index.html中
"""
import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# 确保src目录在path中
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, PROJECT_ROOT
from track_manager import load_config, save_config, get_enabled_tracks
from data_sync import pull_data, push_data

app = FastAPI(title="wxarticle 控制台", version="2.0")

# 静态文件
STATIC_DIR = Path(__file__).parent / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# 生成任务状态
_generation_status = {
    "running": False,
    "progress": "",
    "track_name": "",
    "results": [],
    "started_at": None,
    "finished_at": None,
}

# 定时任务状态
_scheduler_running = False


def _start_scheduler():
    """启动定时生成检查（每60秒检查一次是否到了设定时间）"""
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True

    def _check_loop():
        while True:
            try:
                config = load_config()
                schedule = config.get("schedule", {})
                target_time = schedule.get("time", "08:00")
                
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")
                
                if current_time == target_time:
                    today_dir = OUTPUT_DIR / current_date
                    if today_dir.exists() and any(today_dir.iterdir()):
                        time.sleep(60)
                        continue
                    
                    print(f"[SCHEDULER] 定时触发：{target_time}")
                    trigger_generate()
            except Exception as e:
                print(f"[SCHEDULER] 检查出错: {e}")
            
            time.sleep(60)

    thread = threading.Thread(target=_check_loop, daemon=True)
    thread.start()


# 启动时拉取持久化数据 + 启动定时器
@app.on_event("startup")
async def startup_sync():
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
    for date_dir in OUTPUT_DIR.iterdir():
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


# ============ API 路由 ============

@app.get("/api/articles")
def list_articles():
    """列出所有已生成的文章，扁平列表（不按日期嵌套），按时间倒序"""
    if not OUTPUT_DIR.exists():
        return {"articles": []}

    articles = []
    # 遍历 output/日期/赛道名_N/ 目录
    for date_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for article_dir in sorted(date_dir.iterdir(), reverse=True):
            if not article_dir.is_dir():
                continue

            meta_path = article_dir / "meta.json"
            cover_path = article_dir / "cover.jpg"
            html_path = article_dir / "article_content.html"

            # 从目录名解析赛道名和序号
            dir_name = article_dir.name
            track_name = dir_name
            seq = 0
            # 支持 "情感赛道_1" 格式
            if "_" in dir_name and dir_name.split("_")[-1].isdigit():
                parts = dir_name.rsplit("_", 1)
                track_name = parts[0]
                seq = int(parts[1])

            article_info = {
                "id": f"{date_dir.name}/{dir_name}",  # 唯一ID
                "date": date_dir.name,
                "track": track_name,
                "seq": seq,
                "has_cover": cover_path.exists(),
                "has_html": html_path.exists(),
                "title": dir_name,
                "summary": "",
                "word_count": 0,
                "generated_at": "",
                "topic_reason": "",
                "topic_source": "",
                "status": "done",
            }

            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                article_info.update({
                    "title": meta.get("title", dir_name),
                    "summary": meta.get("summary", ""),
                    "word_count": meta.get("word_count", 0),
                    "generated_at": meta.get("generated_at", ""),
                })
                # 状态
                if meta.get("status") == "generating":
                    article_info["status"] = "generating"
                elif meta.get("status") == "failed":
                    article_info["status"] = "failed"
                # 选题原因
                hot_topic = meta.get("hot_topic", {})
                if hot_topic:
                    reason = hot_topic.get("reason", "")
                    angle = hot_topic.get("angle", "")
                    original = hot_topic.get("original_topic", "")
                    parts = []
                    if original:
                        parts.append(f"热点：{original}")
                    if reason:
                        parts.append(reason)
                    if angle and angle != "直接切入":
                        parts.append(f"角度：{angle}")
                    article_info["topic_reason"] = " | ".join(parts)
                    article_info["topic_source"] = original

            articles.append(article_info)

    # 按生成时间倒序
    articles.sort(key=lambda a: a.get("generated_at") or a["date"], reverse=True)
    return {"articles": articles}


@app.get("/api/articles/{date}/{track_dir}")
def get_article_detail(date: str, track_dir: str):
    """获取单篇文章详情"""
    article_dir = OUTPUT_DIR / date / track_dir
    if not article_dir.exists():
        raise HTTPException(status_code=404, detail="文章不存在")

    result = {
        "date": date,
        "track_dir": track_dir,
        "files": [],
    }

    # 读取meta
    meta_path = article_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        result["meta"] = meta

    # 列出所有文件
    for f in sorted(article_dir.iterdir()):
        if f.is_file():
            result["files"].append({
                "name": f.name,
                "size": f.stat().st_size,
                "type": f.suffix.lstrip("."),
            })

    # 读取HTML内容（预览用）
    html_path = article_dir / "article_content.html"
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            result["html_content"] = f.read()

    # 读取纯文本（复制简介用）
    txt_path = article_dir / "article.txt"
    if txt_path.exists():
        with open(txt_path, "r", encoding="utf-8") as f:
            result["text_content"] = f.read()

    return result


@app.get("/api/articles/{date}/{track_dir}/cover")
def download_cover(date: str, track_dir: str):
    """下载封面图"""
    cover_path = OUTPUT_DIR / date / track_dir / "cover.jpg"
    if not cover_path.exists():
        raise HTTPException(status_code=404, detail="封面图不存在")
    return FileResponse(
        cover_path,
        media_type="image/jpeg",
        filename=f"{track_dir}_cover.jpg",
    )


@app.get("/api/articles/{date}/{track_dir}/html")
def download_html(date: str, track_dir: str):
    """下载排版HTML"""
    html_path = OUTPUT_DIR / date / track_dir / "article_content.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="HTML文件不存在")
    return FileResponse(
        html_path,
        media_type="text/html",
        filename=f"{track_dir}_article.html",
    )


@app.get("/api/articles/{date}/{track_dir}/preview")
def preview_article(date: str, track_dir: str):
    """预览文章"""
    html_path = OUTPUT_DIR / date / track_dir / "article.html"
    if not html_path.exists():
        html_path = OUTPUT_DIR / date / track_dir / "article_content.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="预览页面不存在")

    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)


@app.get("/api/settings")
def get_settings():
    """获取当前设置"""
    config = load_config()

    settings = {
        "tracks": [],
        "generation": config.get("generation", {}),
        "schedule": config.get("schedule", {}),
    }

    for track in config.get("tracks", []):
        settings["tracks"].append({
            "name": track["name"],
            "enabled": track.get("enabled", True),
            "keywords": track.get("keywords", []),
            "articles_per_day": track.get("articles_per_day", 1),
        })

    return settings


@app.put("/api/settings")
def update_settings(settings: dict):
    """更新设置"""
    config = load_config()

    # 更新赛道启用状态和篇数
    if "tracks" in settings:
        for track_update in settings["tracks"]:
            for track in config.get("tracks", []):
                if track["name"] == track_update["name"]:
                    if "enabled" in track_update:
                        track["enabled"] = track_update["enabled"]
                    if "articles_per_day" in track_update:
                        track["articles_per_day"] = track_update["articles_per_day"]

    # 更新生成设置
    if "generation" in settings:
        config["generation"].update(settings["generation"])

    # 更新定时设置
    if "schedule" in settings:
        config["schedule"].update(settings["schedule"])

    save_config(config)
    return {"status": "ok", "message": "设置已保存"}


@app.post("/api/generate")
def trigger_generate(track_name: str = ""):
    """触发文章生成（异步），可指定赛道"""
    if _generation_status["running"]:
        return {"status": "already_running", "message": "已有生成任务在运行中"}

    # 在外面获取赛道列表
    tracks = get_enabled_tracks()
    if track_name:
        tracks = [t for t in tracks if t["name"] == track_name]
        if not tracks:
            return {"status": "error", "message": f"赛道 '{track_name}' 不存在或未启用"}

    if not tracks:
        return {"status": "error", "message": "没有启用的赛道，请检查 config.yaml"}

    # 在主线程中提前创建 generating 占位，确保前端刷新时能立刻看到
    date_str = datetime.now().strftime("%Y-%m-%d")
    pending_dirs = []
    pre_assigned_dirs = {}
    for track in tracks:
        from main import _get_next_output_dir
        out_dir = _get_next_output_dir(date_str, track["name"])
        out_dir.mkdir(parents=True, exist_ok=True)
        # 写入生成中的 meta
        meta = {
            "track": track["name"],
            "title": f"正在生成：{track['name']}文章...",
            "summary": "文章正在生成中，请稍候",
            "word_count": 0,
            "generated_at": datetime.now().isoformat(),
            "status": "generating",
        }
        with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        pending_dirs.append(out_dir)
        pre_assigned_dirs[track["name"]] = str(out_dir)

    def _monitor(proc):
        _generation_status["running"] = True
        _generation_status["progress"] = "正在生成..."
        _generation_status["track_name"] = track_name
        _generation_status["results"] = []
        _generation_status["started_at"] = datetime.now().isoformat()
        _generation_status["finished_at"] = None

        success = False
        try:
            # 轮询子进程状态，避免 wait() 阻塞问题
            deadline = time.time() + 600  # 最多等10分钟
            while time.time() < deadline:
                retcode = proc.poll()
                if retcode is not None:
                    success = retcode == 0
                    break
                time.sleep(2)
            else:
                proc.kill()
                _generation_status["progress"] = "错误: 超时（10分钟）"
            if retcode is not None:
                _generation_status["progress"] = "完成" if success else "生成失败"
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            _generation_status["progress"] = f"错误: {e}"
        finally:
            if not success:
                # 生成失败：将占位目录标记为 failed（不删除，保留现场）
                for d in pending_dirs:
                    meta_path = d / "meta.json"
                    if meta_path.exists():
                        try:
                            with open(meta_path, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            meta["status"] = "failed"
                            meta["title"] = f"生成失败：{meta.get('track', '未知')}赛道"
                            meta["summary"] = "文章生成失败，请重试"
                            with open(meta_path, "w", encoding="utf-8") as f:
                                json.dump(meta, f, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
            # 成功时不需要处理占位——子进程会覆盖 meta.json 和文件
            _generation_status["running"] = False
            _generation_status["finished_at"] = datetime.now().isoformat()
            # push_data 在后台线程执行，不阻塞 monitor
            threading.Thread(target=push_data, daemon=True).start()

    # 用子进程运行生成，完全隔离，崩了不影响 uvicorn
    import subprocess
    cmd = [sys.executable, str(PROJECT_ROOT / "src" / "main.py")]
    if track_name:
        cmd.extend(["--track", track_name])
    env = os.environ.copy()
    # 通过环境变量传递预分配目录，子进程会生成到同一个目录
    env["WX_PRE_ASSIGNED_DIRS"] = json.dumps(pre_assigned_dirs, ensure_ascii=True)
    env["PYTHONUNBUFFERED"] = "1"  # 确保子进程输出不缓冲
    log_file = PROJECT_ROOT / "generate.log"
    try:
        # Windows 下使用 CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS
        # 让子进程完全独立于父进程，不继承文件句柄
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        log_fh = open(str(log_file), "wb")
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT), env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        # 关闭文件句柄，让子进程完全独立持有
        log_fh.close()
    except Exception as e:
        print(f"[GEN] 启动子进程失败: {e}")
        # 标记占位为失败
        for d in pending_dirs:
            meta_path = d / "meta.json"
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    meta["status"] = "failed"
                    meta["title"] = f"生成失败：{meta.get('track', '未知')}赛道"
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
        _generation_status["running"] = False
        _generation_status["progress"] = f"启动子进程失败: {e}"
        return {"status": "error", "message": f"启动子进程失败: {e}"}

    track_names = [t["name"] for t in tracks]
    thread = threading.Thread(target=_monitor, args=(proc,), daemon=True)
    thread.start()

    return {"status": "started", "message": "生成任务已启动", "tracks": track_names}


@app.get("/api/log")
def get_generate_log(lines: int = 100):
    """查看最近的生成日志"""
    from fastapi.responses import PlainTextResponse
    log_file = PROJECT_ROOT / "generate.log"
    if not log_file.exists():
        return PlainTextResponse("(无日志)", media_type="text/plain; charset=utf-8")
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
        content = "".join(all_lines[-lines:])
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")


@app.get("/api/generate/status")
def get_generation_status():
    """获取生成任务状态"""
    return _generation_status


@app.post("/api/update")
def self_update():
    """从GitHub拉取最新代码并更新（保留.env和output）
    支持GitHub镜像加速，国内服务器也可正常更新
    """
    import urllib.request
    import zipfile

    # GitHub直连 + 国内镜像，按顺序尝试
    zip_urls = [
        "https://ghfast.top/https://github.com/iamzhangg/wxarticle/archive/refs/heads/master.zip",
        "https://ghproxy.net/https://github.com/iamzhangg/wxarticle/archive/refs/heads/master.zip",
        "https://github.com/iamzhangg/wxarticle/archive/refs/heads/master.zip",
    ]
    zip_path = PROJECT_ROOT / "_update.zip"
    extract_dir = PROJECT_ROOT / "_update_tmp"

    try:
        # 下载（尝试多个镜像）
        downloaded = False
        last_err = None
        for url in zip_urls:
            try:
                urllib.request.urlretrieve(url, str(zip_path))
                # 验证文件大小
                if zip_path.stat().st_size > 1000:
                    downloaded = True
                    break
                else:
                    zip_path.unlink(missing_ok=True)
            except Exception as e:
                last_err = e
                zip_path.unlink(missing_ok=True)
                continue

        if not downloaded:
            return {"status": "error", "message": f"所有下载源均失败: {last_err}"}

        # 解压
        with zipfile.ZipFile(str(zip_path), "r") as z:
            z.extractall(str(extract_dir))

        # 找到解压后的目录（master分支解压后为wxarticle-master）
        inner = None
        for name in ["wxarticle-master", "wxarticle-main"]:
            if (extract_dir / name).exists():
                inner = extract_dir / name
                break
        if not inner:
            for d in extract_dir.iterdir():
                if d.is_dir():
                    inner = d
                    break

        if not inner:
            return {"status": "error", "message": "解压后未找到项目目录"}

        # 复制关键目录和文件（保留 .env、output、venv、config.yaml）
        for item in ["src", "tracks", "assets", "start_web.py", "requirements.txt", "README.md", ".env.example"]:
            src = inner / item
            dst = PROJECT_ROOT / item
            if src.exists():
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(str(dst))
                    shutil.copytree(str(src), str(dst))
                elif src.is_file():
                    shutil.copy2(str(src), str(dst))

        # 安装新依赖（如果有变化）
        try:
            import subprocess
            pip_path = PROJECT_ROOT / "venv" / "Scripts" / "pip.exe"
            if pip_path.exists():
                subprocess.run(
                    [str(pip_path), "install", "-r", str(PROJECT_ROOT / "requirements.txt")],
                    capture_output=True, timeout=120
                )
        except Exception:
            pass  # 依赖安装失败不阻塞更新

        # 清理
        zip_path.unlink(missing_ok=True)
        if extract_dir.exists():
            shutil.rmtree(str(extract_dir))

        return {"status": "ok", "message": "更新成功，正在自动重启服务..."}
    except Exception as e:
        # 清理
        zip_path.unlink(missing_ok=True)
        if extract_dir.exists():
            shutil.rmtree(str(extract_dir))
        return {"status": "error", "message": f"更新失败: {e}"}


@app.post("/api/restart")
def restart_service():
    """重启wxarticle服务（通过启动新进程后退出当前进程）"""
    import subprocess

    try:
        # 启动新进程
        python = sys.executable
        script = PROJECT_ROOT / "start_web.py"

        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

        subprocess.Popen(
            [python, str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs
        )

        # 延迟退出当前进程，确保新进程启动
        threading.Timer(1.0, lambda: os._exit(0)).start()

        return {"status": "ok", "message": "重启中..."}
    except Exception as e:
        return {"status": "error", "message": f"重启失败: {e}"}


@app.delete("/api/articles/{date}/{track_dir}")
def delete_article(date: str, track_dir: str):
    """删除指定文章"""
    article_dir = OUTPUT_DIR / date / track_dir
    if not article_dir.exists():
        raise HTTPException(status_code=404, detail="文章不存在")

    shutil.rmtree(article_dir)
    return {"status": "ok", "message": f"已删除 {date}/{track_dir}"}


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

def run_server(host: str = "0.0.0.0", port: int = 8080):
    """启动Web服务器"""
    import uvicorn
    print(f"[WEB] wxarticle 控制台启动: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="wxarticle Web控制台")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
