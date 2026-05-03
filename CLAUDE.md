# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

wxarticle v2 — 微信公众号文章自动生成工具（赛道制）。AI写稿 + 自动配图 + 微信排版 + Web控制台。所有AI能力通过硅基流动（SiliconFlow）API调用。

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
2. `topic_searcher` 从头条/搜狗微信搜索热门选题
3. `article_generator` 调用 Qwen3-235B 生成文章（卡兹克风格 + 赛道约束 + L1自检）
4. 根据 `IMAGE_SOURCE` 配置走 `image_generator`（AI生图 Kolors）或 `image_searcher`（Pexels/Pixabay图库）
5. `formatter` 将Markdown转为微信公众号兼容HTML（紫色系排版、base64图片内嵌；默认2张正文插图尽量放在1/3、2/3位置）
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
├── article_content.html   # 纯内容片段（可直接粘贴到公众号编辑器）
├── article.md             # Markdown原文
├── article.txt            # 纯文本
├── meta.json              # 元信息（标题、简介、字数、选题等）
├── inline_1.jpg           # 正文插图（16:9横向）
└── inline_2.jpg
```

## 关键设计决策

- 微信编辑器忽略 `<style>` 标签，只认 inline style，因此所有元素通过 `_inject_no_background()` 逐元素注入 `style="background:none;"` 确保无底色
- 图片在HTML中 base64 内嵌，复制到微信后图片自动上传到微信服务器，不依赖外部图床
- 默认生成2张正文插图，排版时靠近正文1/3和2/3处，让内容自然分成三段
- Windows下的子进程生成使用 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` 确保进程完全独立
- 文章生成在 `generate.log` 中有详细日志（子进程stdout/stderr都写到这里）

## 服务器部署

目标服务器：腾讯云轻量应用服务器（Windows Server + 宝塔面板），公网 IP `123.207.199.142`。

### 部署命令（一行）

```powershell
# 首次部署
Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/iamzhangg/wxarticle/master/deploy_windows.ps1 | iex
```

### 部署踩坑总结

**1. GitHub Token 的 workflow scope 问题**
- Classic token 必须在创建时勾选 `workflow` 范围，否则无法通过 git push 和 API 上传 `.github/workflows/` 目录下的文件
- 报错: `refusing to allow a Personal Access Token to create or update workflow`
- 解决: 去 GitHub Settings → Developer settings → Tokens → 勾选 workflow → 重新生成

**2. PowerShell 多行命令的换行问题**
- 用户从对话框复制长命令到 PowerShell 时，换行符会被解析为执行，导致参数被拆开
- 症状: `无法将"-ArgumentList"项识别为 cmdlet`
- 解决: 用分号 `;` 串联多条命令，或写 `.ps1` 脚本文件再用 `powershell -File` 执行

**3. `.env` 文件编码问题**
- 用 `echo` 写入中文内容可能产生 GBK 编码，Python `dotenv` 读 UTF-8 时报错
- 报错: `UnicodeDecodeError: 'utf-8' codec can't decode bytes`
- 解决:
  ```powershell
  cmd /c "echo KEY=value> .env"  # 纯英文内容，避免编码问题
  ```

**4. `pythonw.exe` 在 venv 中不存在**
- venv 的 `Scripts/` 目录下只有 `python.exe`，没有 `pythonw.exe`
- 无法用 `pythonw.exe` 实现无窗口启动
- 解决: 用 Windows 计划任务 `schtasks` 在后台运行服务，计划任务不会弹出窗口

**5. 服务常驻后台的正确方式**
- 不要依赖 PowerShell 窗口保持打开
- 正确做法:
  ```powershell
  # 查看任务
  schtasks /query /tn wxarticle
  # 手动触发
  schtasks /run /tn wxarticle
  # 停止（找进程杀）
  taskkill /f /im python.exe
  ```
- 计划任务配置: 开机自启 + 失败后每分钟重试（最多99次）

**6. 公网访问推荐走宝塔反向代理**
- Python 服务默认只监听 `127.0.0.1:8080`
- 宝塔/Nginx 站点反向代理到 `http://127.0.0.1:8080`
- 给站点加 Basic Auth、登录态或腾讯云防火墙白名单后再暴露公网
- 临时公网直连才设置 `HOST=0.0.0.0` 并放行 TCP 8080，不建议长期裸露

**7. 服务更新流程**
```powershell
# 方法1: Web控制台自更新（推荐）
# POST http://IP:8080/api/update （从 GitHub 拉取最新代码 + 自动重启）

# 方法2: 手动更新
cd C:\Users\Administrator\wxarticle\wxarticle-master
taskkill /f /im python.exe
git pull
.\venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 然后 schtasks 或手动启动
```

**8. pip 国内加速**
- 服务器在国内时，用清华镜像避免下载超时:
  ```powershell
  pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```

**9. GitHub 下载加速**
- 国内服务器下载 GitHub 文件，用镜像代理:
  - `https://ghfast.top/https://github.com/...`
  - 或者 `ghproxy.net`
- 项目 `POST /api/update` 已内置多镜像自动切换

**10. 无 git 时的部署方案**
- 如果服务器没装 git，用 ZIP 下载: `https://github.com/iamzhangg/wxarticle/archive/refs/heads/master.zip`
- `Expand-Archive` 解压后目录名为 `wxarticle-master`
- 注意 `cd` 路径要匹配实际解压出来的目录名
