# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

wxarticle v2 — 内容平台文章自动生成工具（赛道制）。AI写稿 + 自动配图 + 内容排版 + Web控制台。所有AI能力通过硅基流动（SiliconFlow）API调用。

## 常用命令

```bash
# 启动Web控制台（主要入口，默认仅本机访问）
python start_web.py                    # http://localhost:8080
# 局域网/云服务器访问需显式设置 HOST=0.0.0.0，并配合鉴权或防火墙

# 命令行生成
python src/main.py                     # 所有启用的赛道
python src/main.py --track 生活赛道     # 指定赛道
python src/main.py --dry-run --skip-search  # 测试模式，不调API

# 安装依赖
pip install -r requirements.txt
```

无测试套件，无lint配置。验证方式为 `python src/main.py --dry-run --skip-search` 跑通流程。

## 架构

### 主流程（`src/main.py`）

单赛道流程 `process_track()`：
1. `track_manager` 读取赛道配置（`config.yaml` + `tracks/{赛道名}/prompt.md`）
2. `topic_searcher` 从头条/搜狗内容搜索热门选题
3. `article_generator` 调用 Qwen3-235B 生成文章（卡兹克风格 + 赛道约束 + L1自检）
4. 根据 `IMAGE_SOURCE` 配置走 `image_generator`（AI生图 Kolors）或 `image_searcher`（Pexels/Pixabay图库）
5. `formatter` 将Markdown转为内容平台兼容HTML（紫色系排版、base64图片内嵌；默认2张正文插图尽量放在1/3、2/3位置）
6. 保存到 `output/{日期}/{赛道名}/`

`articles_per_day` 会展开为同一赛道的多篇任务；Web 触发生成时会提前为每篇文章预分配输出目录，并通过 `WX_PRE_ASSIGNED_DIRS` 传给子进程。

图片来源模块（`image_generator.py` vs `image_searcher.py`）在 `main.py` 顶部按 `IMAGE_SOURCE` 值做 import 级别切换，两个模块暴露相同的函数签名 `generate_cover_image()` / `generate_inline_image()`。

### Web控制台（`src/web_app.py`）

FastAPI后端，前端SPA在 `src/web/static/index.html`。核心API：
- `GET /api/articles` — 文章列表
- `POST /api/generate` — 手动触发生成（通过子进程调用 `src/main.py`，10分钟超时，状态通过占位 `meta.json` 的 `status` 字段传递）
- `PUT /api/settings` — 更新 `config.yaml`
- `POST /api/update` — 从GitHub拉取最新代码自更新
- `POST /api/restart` — 重启服务

内置简易定时器（60秒轮询），到 `config.yaml` 中 `schedule.time` 时刻自动触发当日生成。

Web 服务默认监听 `127.0.0.1`。所有文章文件接口必须通过 `_get_article_dir()` / `_resolve_output_path()` 校验，确保请求路径仍在 `OUTPUT_DIR` 内；生成入口使用 `_generation_lock` 防止并发触发。子进程生成前会清理 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 等代理环境变量，避免本机代理干扰硅基流动 API。

### 文章生成器（`src/article_generator.py`）

核心约束体系（优先级递减）：
1. **赛道写作约束**（`tracks/{赛道名}/prompt.md`）— 硬性规则，不可违反
2. **卡兹克风格指南**（从 `~/.workbuddy/skills/khazix-writer/SKILL.md` 加载）— 默认写作方式

自检机制：L1禁用词/禁用标点扫描 → 超标（>5个hits或>3个结构问题）自动重试，少量问题自动修复。

### 配置层级（`src/config.py`）

环境变量 `.env` > `config.yaml` > 代码默认值。API密钥只存在于 `.env`，赛道/生成/定时配置在 `config.yaml`。

### 赛道系统（`src/track_manager.py` + `tracks/`）

每个赛道目录包含 `prompt.md`（写作约束）。`config.yaml` 中定义赛道的 `enabled`、`keywords`、`articles_per_day`、`search_sources`、`image_style`。

### 数据持久化（`src/data_sync.py`）

通过环境变量 `DATA_GIT_REPO` / `DATA_GIT_TOKEN` 配置，将 `output/` 目录同步到GitHub的 `data` 分支。不配置也能正常运行（纯本地模式）。

### 涉及的AI模型（全部硅基流动）

| 用途 | 模型 | 调用方式 |
|------|------|---------|
| 文章写作 | Qwen3-235B | `requests` 直接调用 `/chat/completions` |
| 选题筛选/prompt翻译/关键词生成 | Qwen3-8B | `openai` SDK |
| 封面图/插图生成 | Kwai-Kolors/Kolors | `requests` 直接调用 `/images/generations` |

## 输出目录结构

```
output/{日期}/{赛道名}/
├── cover.jpg              # 封面图（900×383, 2.35:1）
├── article.html           # 完整可预览HTML（手机框架预览）
├── article_content.html   # 纯内容片段（可直接粘贴到内容平台编辑器）
├── article.md             # Markdown原文
├── article.txt            # 纯文本
├── meta.json              # 元信息（标题、简介、字数、选题等）
├── inline_1.jpg           # 正文插图（16:9横向）
└── inline_2.jpg
```

## 关键设计决策

- 富文本编辑器忽略 `<style>` 标签，只认 inline style，因此所有元素通过 `_inject_no_background()` 逐元素注入 `style="background:none;"` 确保无底色
- 图片在HTML中 base64 内嵌，复制排版后图片自动上传到平台服务器，不依赖外部图床
- 默认生成2张正文插图，排版时靠近正文1/3和2/3处，让内容自然分成三段
- Windows下的子进程生成使用 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` 确保进程完全独立
- 文章生成在 `generate.log` 中有详细日志（子进程stdout/stderr都写到这里）

## 服务器部署

目标环境是腾讯云轻量应用服务器（Windows Server + 宝塔面板）。部署入口：

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/iamzhangg/wxarticle/master/deploy_windows.ps1 | iex
```

脚本从 GitHub 拉取 `master` 到 `C:\wxarticle`，创建 venv，安装依赖，注册开机自启任务 `wxarticle`。服务默认只监听 `127.0.0.1:8080`，公网访问推荐在宝塔/Nginx 里反向代理到 `http://127.0.0.1:8080`，并加 Basic Auth、登录态或腾讯云防火墙白名单。临时公网直连才设置 `HOST=0.0.0.0` 并放行 TCP 8080。
