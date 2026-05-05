# TECH_STACK.md

## 1. 项目定位

`wxarticle v2` 是一个文章生成、排版与发布推送自动化工具。当前 MVP 已跑通：

- 通过 Web 控制台管理赛道、配置和生成任务。
- 按赛道搜索选题、调用 AI 生成文章。
- 自动生成封面图和正文配图。
- 输出适合富文本编辑器粘贴的 HTML 内容。
- 支持本地运行，也支持 Windows Server 后台常驻运行。

当前主要运行方式：

```bash
python start_web.py
```

默认监听：

```text
127.0.0.1:8080
```

公网访问建议通过反向代理，并增加访问认证或防火墙限制。

## 2. 核心目录结构

```text
wxarticle/
├── start_web.py                 # Web 控制台启动入口
├── config.yaml                  # 赛道、生成、定时等业务配置
├── requirements.txt             # Python 依赖
├── deploy_windows.ps1           # Windows Server 部署辅助脚本
├── README.md                    # 面向公开用户的项目说明
├── docs/
│   └── deployment.md            # 可选部署说明
├── src/
│   ├── web_app.py               # FastAPI Web 后端与 API 路由
│   ├── web/static/index.html    # Web 控制台前端 SPA
│   ├── main.py                  # 文章生成主流程
│   ├── config.py                # 配置读取与环境变量合并
│   ├── track_manager.py         # 赛道配置加载与保存
│   ├── topic_searcher.py        # 热点/选题搜索与筛选
│   ├── article_generator.py     # AI 文章生成与自检
│   ├── article_parser.py        # 文章结构解析
│   ├── formatter.py             # Markdown/文章内容转 HTML 排版
│   ├── image_generator.py       # AI 生图
│   ├── image_searcher.py        # 图库搜索模式
│   ├── image_uploader.py        # 图片上传能力
│   └── data_sync.py             # output 数据同步到 GitHub data 分支，可选
├── tracks/
│   ├── AI赛道/prompt.md
│   ├── 人物赛道/prompt.md
│   ├── 感悟赛道/prompt.md
│   ├── 生活赛道/prompt.md
│   └── 高校赛道/prompt.md
├── output/
│   └── YYYY-MM-DD/赛道名/       # 每篇文章的生成结果
├── assets/
│   └── guides/                  # 排版参考素材
└── .github/workflows/
    └── daily.yml                # 可选 GitHub Actions 定时生成
```

典型文章输出目录：

```text
output/{日期}/{赛道名}/
├── cover.jpg
├── article.html
├── article_content.html
├── article.md
├── article.txt
├── meta.json
├── inline_1.jpg
└── inline_2.jpg
```

## 3. 技术栈

### 后端

| 类型 | 技术/库 | 用途 |
| --- | --- | --- |
| 语言 | Python | 主开发语言 |
| Web 框架 | FastAPI | Web 控制台 API |
| ASGI Server | Uvicorn | 本地/服务器启动 Web 服务 |
| HTTP 请求 | requests | 调用外部搜索、AI、生图接口 |
| AI SDK | openai | 兼容 OpenAI SDK 的模型调用 |
| 配置 | python-dotenv, PyYAML | 读取 `.env` 与 `config.yaml` |
| HTML 解析 | beautifulsoup4, lxml | HTML 清洗、排版处理 |
| 图片处理 | Pillow | 封面图、正文配图处理 |

### 前端

当前前端是一个轻量级单文件 SPA：

```text
src/web/static/index.html
```

特点：

- 未使用 React/Vue/Svelte 等前端框架。
- 主要由原生 HTML、CSS、JavaScript 实现。
- 通过 `fetch` 调用 FastAPI 接口。
- 适合 MVP 快速迭代，但后续复杂度上来后建议组件化。

### AI 与外部服务

| 能力 | 当前实现 |
| --- | --- |
| 文章生成 | SiliconFlow API，模型配置在 `config.yaml` / 环境变量中 |
| 选题筛选 | SiliconFlow/OpenAI SDK 兼容调用 |
| AI 生图 | SiliconFlow 图像生成接口 |
| 图库搜索 | Pexels / Pixabay，可选 |
| 数据同步 | GitHub data 分支，可选，需要 `DATA_GIT_REPO` / `DATA_GIT_TOKEN` |

### 部署与运行

| 场景 | 当前方案 |
| --- | --- |
| 本地开发 | `python start_web.py` |
| Windows Server 常驻 | Windows 计划任务 + `run_web.bat` |
| 反向代理 | Nginx / 宝塔反向代理到 `http://127.0.0.1:8080` |
| 容器化 | 已有 Dockerfile 草案，但暂未纳入主发布范围；容器化部署尚未验证 |
| 定时生成 | 应用内 60 秒轮询 `config.yaml` 中的 `schedule.time` |

## 4. 主要业务流程

### Web 手动生成

```text
浏览器
  -> FastAPI /api/generate
  -> 创建生成任务状态
  -> 子进程执行 src/main.py
  -> 按赛道生成文章、图片、HTML
  -> 写入 output/
  -> Web 控制台读取结果
```

### 单篇文章生成

```text
加载 config.yaml 和 tracks/{赛道}/prompt.md
  -> 搜索热点选题
  -> AI 筛选角度
  -> AI 生成文章
  -> 内容自检和修复
  -> 生成/搜索封面与正文图
  -> formatter 输出 HTML
  -> 写入 output/{日期}/{赛道名}/
```

## 5. 当前技术债

### P1：Web 控制台缺少正式认证体系

当前服务默认监听 `127.0.0.1`，这个选择是安全的。但如果通过公网反向代理暴露，仍需要额外保护。

建议后续补齐：

- 登录态或 API Token。
- 所有写接口鉴权，包括生成、修改配置、删除文章、自更新、重启。
- 基础操作审计日志。
- 公网部署文档中明确认证和防火墙要求。

### P1：前端单文件过大

当前前端集中在：

```text
src/web/static/index.html
```

该文件包含页面结构、样式、交互逻辑和 API 调用。MVP 阶段可接受，但后续维护成本会升高。

建议拆分：

- `api.js`：统一封装 API 请求。
- `state.js`：管理生成状态、设置状态、文章列表状态。
- `components/`：文章列表、设置面板、预览区、生成面板。
- `styles.css`：样式独立维护。

如后续功能继续增加，可考虑迁移到 Vite + React/Vue。

### P1：`src/web_app.py` 职责过多

当前 `web_app.py` 同时承担：

- FastAPI app 初始化。
- 静态文件服务。
- 文章列表/预览/删除 API。
- 设置读写 API。
- 生成任务调度。
- 子进程管理。
- 定时任务。
- 数据同步触发。

文件约 600 行，已经接近需要拆分的程度。

建议拆分：

```text
src/web/
├── app.py
├── routes/
│   ├── articles.py
│   ├── generation.py
│   ├── settings.py
│   └── system.py
├── services/
│   ├── generation_runner.py
│   ├── scheduler.py
│   └── article_store.py
└── security.py
```

### P1：`src/formatter.py` 过于臃肿

`formatter.py` 约 900 行，当前承担：

- Markdown 行级解析。
- HTML 生成。
- 图片插入位置计算。
- 样式注入。
- 富文本兼容处理。
- 完整预览页面生成。

这是项目中最值得优先拆的文件之一。

建议拆分：

```text
src/formatting/
├── markdown_parser.py
├── html_renderer.py
├── image_placement.py
├── style_inliner.py
└── preview_page.py
```

### P2：AI 调用层还没有统一抽象

目前文章生成、选题筛选、生图等能力分散在多个模块中，部分用 `requests`，部分用 `openai` SDK。

建议后续抽象：

```text
src/ai/
├── client.py
├── text_generation.py
├── image_generation.py
└── prompt_templates.py
```

收益：

- 统一超时、重试、错误处理。
- 统一日志和 token/成本统计。
- 后续切换模型供应商更容易。

### P2：生成任务状态仍偏内存化

Web 生成状态主要依赖内存字典和输出目录里的 `meta.json`。服务重启后可以清理残留状态，但还不是完整任务系统。

建议后续：

- 引入轻量任务表，例如 SQLite。
- 每次生成有独立 `job_id`。
- 记录任务状态、开始时间、结束时间、错误信息、输出目录。
- 前端按 `job_id` 轮询状态。

### P2：缺少自动化测试

当前没有测试套件和 lint 配置。验证方式主要是：

```bash
python src/main.py --dry-run --skip-search
```

建议补齐：

- `pytest`：覆盖配置读取、路径安全、formatter 基础转换、文章输出结构。
- `ruff`：统一格式和基础静态检查。
- Web API smoke test：至少覆盖 `/api/articles`、`/api/settings`、`/api/generate` 的基本路径。

### P2：部署脚本仍偏 Windows 特定

当前 Windows Server 部署已经跑通，但部署链路仍带有较强的个人服务器经验色彩。

建议沉淀为两层：

- 通用部署：Python venv + env + reverse proxy。
- Windows Server 示例：计划任务、宝塔、PowerShell helper。

长期看可以补充：

- Docker Compose。
- systemd 示例。
- Nginx Basic Auth 示例。
- 备份和迁移说明。

### P3：仓库中存在历史临时脚本和截图资产

根目录有一些早期调试/部署辅助文件，例如：

```text
bt_deploy_new.py
bt_screenshot.py
_deploy_koyeb.py
_push_to_github.py
_server_deploy.py
*.png
*.zip
*.log
```

这些文件对 MVP 探索有价值，但对公开项目和团队交接会造成噪音。

建议后续：

- 确认仍需保留的脚本移动到 `scripts/`。
- 部署截图移动到 `docs/assets/` 或删除。
- 日志、临时 zip、个人部署脚本不要进入版本库。
- 保持根目录只放入口文件、配置、文档和标准工程文件。

## 6. 配置与密钥

配置来源优先级：

```text
.env > config.yaml > 代码默认值
```

核心配置：

| 文件 | 用途 |
| --- | --- |
| `.env` | API Key、图片源、数据同步 token 等敏感配置，不应提交 |
| `.env.example` | 公开示例配置 |
| `config.yaml` | 赛道、关键词、生成数量、模型、定时任务等业务配置 |
| `tracks/*/prompt.md` | 每个赛道的写作约束 |

敏感项示例：

```text
SILICONFLOW_API_KEY
PEXELS_API_KEY
PIXABAY_API_KEY
SMMS_TOKEN
DATA_GIT_TOKEN
```

## 7. 运维现状

当前已验证的服务器运行方式：

- Windows Server。
- Python virtualenv。
- `start_web.py` 启动 FastAPI/Uvicorn。
- Windows 计划任务以 `SYSTEM` 用户运行。
- 服务监听 `127.0.0.1:8080`。
- 如需公网访问，通过宝塔/Nginx 反向代理到 `http://127.0.0.1:8080`。

建议生产化要求：

- 不直接监听 `0.0.0.0`。
- 公网访问必须加认证或 IP 白名单。
- 日志写入固定文件，并设置轮转策略。
- `.env` 单独备份，不进入 Git。
- `output/` 目录定期备份。

## 8. 后续重构优先级建议

### 第一阶段：稳定性与安全

- 给 Web 控制台增加认证。
- 为所有写接口加鉴权。
- 增加生成任务错误展示和日志下载。
- 梳理部署文档，补充迁移和备份步骤。

### 第二阶段：模块拆分

- 拆 `formatter.py`。
- 拆 `web_app.py`。
- 抽象 AI client。
- 将前端从单文件拆成多个静态模块。

### 第三阶段：工程化

- 引入 `pytest` 和 `ruff`。
- 增加 CI 验证。
- 整理根目录临时文件。
- 补 Docker Compose 和 Linux systemd 部署示例。

## 9. 交接注意事项

- 不要提交 `.env` 和任何真实 API Key。
- 不要直接公网暴露 Web 控制台。
- 修改 `formatter.py` 前要用真实文章预览验证复制效果。
- 修改生成流程前要跑 `--dry-run --skip-search`。
- 修改文章目录/删除逻辑时必须保留路径越界校验。
- 修改部署脚本后需要在干净 Windows Server 环境验证。
