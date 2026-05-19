from __future__ import annotations
"""
数据持久化模块 - 将生成的文章同步到 GitHub 仓库

工作原理：
1. 启动时：从 GitHub 拉取最新 output/ 数据（如果有）
2. 生成文章后：将新文章推送到 GitHub 的 data/ 分支

环境变量：
- DATA_GIT_REPO: GitHub 仓库地址（如 https://github.com/user/repo）
- DATA_GIT_TOKEN: GitHub Personal Access Token
- DATA_GIT_BRANCH: 存储分支（默认 data）
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from config import OUTPUT_DIR, PROJECT_ROOT


def _get_env():
    """获取 GitHub 配置"""
    repo = os.getenv("DATA_GIT_REPO", "")
    token = os.getenv("DATA_GIT_TOKEN", "")
    branch = os.getenv("DATA_GIT_BRANCH", "data")
    return repo, token, branch


def _clean_repo_url(repo: str) -> str:
    """Remove embedded credentials before saving a remote URL."""
    if "@" in repo and repo.startswith("https://"):
        return "https://" + repo.split("@", 1)[1]
    return repo


def _run_git(cmd: list[str], cwd: str = None, token: str = "") -> tuple[bool, str]:
    """执行 git 命令"""
    askpass_path = None
    try:
        env = os.environ.copy()
        if token:
            fd, askpass_path = tempfile.mkstemp(prefix="wxarticle_git_", suffix=".bat")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("@echo off\n")
                f.write('echo %~1 | findstr /I "Username" >nul\n')
                f.write("if not errorlevel 1 (\n")
                f.write("  echo x-access-token\n")
                f.write(") else (\n")
                f.write("  echo %DATA_GIT_TOKEN%\n")
                f.write(")\n")
            env["GIT_ASKPASS"] = askpass_path
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["DATA_GIT_TOKEN"] = token
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd or str(OUTPUT_DIR), timeout=30, env=env
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)
    finally:
        if askpass_path:
            try:
                os.unlink(askpass_path)
            except OSError:
                pass


def pull_data():
    """启动时从 GitHub 拉取最新文章数据"""
    repo, token, branch = _get_env()
    if not repo or not token:
        print("[DATA] 未配置 DATA_GIT_REPO/DATA_GIT_TOKEN，跳过数据拉取")
        return

    clean_repo = _clean_repo_url(repo)

    # 初始化 git 仓库（如果还没有）
    if not (OUTPUT_DIR / ".git").exists():
        print("[DATA] 初始化数据仓库...")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ok, msg = _run_git(["git", "init"])
        if not ok:
            print(f"[DATA] git init 失败: {msg}")
            return
        _run_git(["git", "remote", "add", "origin", clean_repo])
    else:
        _run_git(["git", "remote", "set-url", "origin", clean_repo])

    # 拉取数据分支
    print(f"[DATA] 从 {branch} 分支拉取最新数据...")
    _run_git(["git", "fetch", "origin", branch], token=token)

    # 尝试切换到数据分支
    ok, msg = _run_git(["git", "checkout", branch])
    if not ok:
        # 分支不存在，创建它
        ok2, msg2 = _run_git(["git", "checkout", "-b", branch])
        if not ok2:
            print(f"[DATA] 创建分支失败: {msg2}")
            return

    ok, msg = _run_git(["git", "pull", "origin", branch], token=token)
    if ok:
        print("[DATA] ✅ 数据拉取成功")
    else:
        print(f"[DATA] 拉取完成（可能首次部署无数据）: {msg[:100]}")


def push_data():
    """生成文章后推送数据到 GitHub"""
    repo, token, branch = _get_env()
    if not repo or not token:
        print("[DATA] 未配置持久化，跳过数据推送")
        return

    clean_repo = _clean_repo_url(repo)

    # 确保远程地址不包含 token，凭证只通过临时 askpass 传递
    _run_git(["git", "remote", "set-url", "origin", clean_repo])

    # 添加所有文件
    _run_git(["git", "add", "."])
    
    # 检查是否有变更
    ok, msg = _run_git(["git", "diff", "--cached", "--quiet"])
    if ok:
        print("[DATA] 没有新的变更需要推送")
        return

    # 提交
    from datetime import datetime
    commit_msg = f"auto: 文章更新 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    _run_git(["git", "config", "user.email", "wxarticle-bot@users.noreply.github.com"])
    _run_git(["git", "config", "user.name", "wxarticle-bot"])
    _run_git(["git", "commit", "-m", commit_msg])

    # 推送
    ok, msg = _run_git(["git", "push", "origin", branch], token=token)
    if ok:
        print("[DATA] ✅ 数据推送成功")
    else:
        print(f"[DATA] 推送失败: {msg[:200]}")


# 不配置 GitHub 也能正常运行——纯本地模式
# pull_data / push_data 会自动跳过
