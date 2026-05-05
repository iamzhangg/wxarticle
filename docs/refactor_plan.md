# Refactor Plan

Last updated: 2026-05-05

Owner: 周衡 / Architecture and Stability

## Scope

本计划只覆盖架构重构、稳定性增强和可维护性建设，不负责产品需求发散、部署发布、生产操作或 GitHub 发布。

当前阶段不直接改业务代码。结构性改造必须先拆清边界、验证方式和回滚路径。

## 当前架构风险

### P0 / 操作边界风险

- Web 控制台具备生成、修改配置、自更新、重启、删除文章等写操作能力，但应用内还没有正式认证与写接口鉴权。默认监听 `127.0.0.1` 是安全底线，一旦经公网反向代理暴露，风险会明显上升。
- `.env`、API Key、数据同步 token 等敏感配置依赖人工边界保护。任何重构都不能读取、输出或改写 `.env`，也不能把密钥写入日志、文档或错误信息。

### P1 / 模块职责过重

- `src/web_app.py` 约 622 行，同时承担 FastAPI 初始化、路由、文章文件访问、配置读写、生成任务调度、子进程管理、定时任务、系统更新和重启。职责混杂会让鉴权、错误处理、任务状态持久化变得难以安全落地。
- `src/formatter.py` 约 909 行，承担 Markdown 解析、HTML 渲染、图片插入位置计算、inline style 注入、富文本兼容处理和完整预览页生成。它直接影响最终复制到内容平台的排版效果，是高风险改动点。
- `src/web/static/index.html` 约 762 行，结构、样式、交互和 API 调用集中在单文件里。MVP 阶段可接受，但继续扩展会放大 UI 状态和接口错误处理成本。

### P1 / 任务状态与失败恢复不足

- 生成状态主要依赖内存状态和输出目录里的 `meta.json`。服务重启、子进程异常、超时、半成品目录残留时，前端和后端都缺少统一可信的任务事实来源。
- 生成任务目前通过子进程运行，日志写入 `generate.log`，但任务状态、错误摘要、输出目录和日志片段之间没有统一索引，不利于排查失败。

### P1 / 路径与文件安全需要持续收紧

- 文档强调文章文件接口必须通过 `_get_article_dir()` / `_resolve_output_path()` 校验，这是正确方向。后续拆分 `web_app.py` 时，路径安全不能散落到各路由里，应该沉到独立 `article_store` 或 `path_guard` 层。
- 删除文章、读取预览、下载封面、读取内容片段等接口都依赖路径边界，拆分时必须先补最小测试，避免重构过程中引入越界读取或误删。

### P2 / AI 调用层分散

- 文章生成、选题筛选、prompt 翻译、关键词生成、AI 生图分别散落在多个模块里，且混用 `requests` 和 `openai` SDK。
- 超时、重试、错误分类、日志、模型配置和成本统计目前难以统一。后续更换供应商或调整模型时，影响面会偏大。

### P2 / 验证体系薄弱

- 项目目前没有正式测试套件和 lint 配置，主要验证命令是 `python src/main.py --dry-run --skip-search`。
- 重构目标文件正好是高风险文件，必须先建立最小自动化保护：路径安全、formatter 基础输出、任务状态转换、Web API smoke test。

## 第一阶段重构顺序

第一阶段目标不是大规模拆文件，而是先降低事故概率，让后续拆分有护栏。

### 1. 建立重构基线

目标：

- 记录当前模块边界、关键入口和验证命令。
- 确认现有行为不被误改，尤其是 Web 生成入口、文章文件访问和 formatter 输出。

建议产出：

- `docs/refactor_plan.md` 持续更新。
- 必要时新增 `docs/architecture.md`，记录最终目标结构和迁移约束。

验证：

```bash
python src/main.py --dry-run --skip-search
```

### 2. 先补路径安全与 formatter 最小测试

目标：

- 在拆分前给最危险的行为加低成本保护。
- 优先覆盖 `_resolve_output_path()`、文章目录解析、formatter 基础 HTML 输出、inline image 插入数量和位置。

建议方式：

- 引入 `pytest` 前先确认依赖策略；如要改 `requirements.txt`，单独说明。
- 测试数据使用临时目录和小样本文本，不依赖真实 `.env` 或外部 API。

原因：

- `web_app.py` 和 `formatter.py` 都是接下来要拆的模块。没有测试直接拆，风险会集中爆发在文章删除、预览读取和复制排版这些用户可见路径上。

### 3. 抽出 Web 文件访问层

目标：

- 先从 `src/web_app.py` 里抽出文章目录扫描、路径解析、文件读取、删除前校验等逻辑。

目标结构建议：

```text
src/web/
├── services/
│   └── article_store.py
└── security.py 或 path_guard.py
```

约束：

- 对外 API 路径和返回结构先保持不变。
- 所有 output 访问必须经过同一个服务层。
- 删除逻辑只做迁移，不扩展功能；真实删除相关调整仍需 Gio 明确确认。

### 4. 抽出生成任务运行层

目标：

- 从 `src/web_app.py` 中分离生成锁、预分配输出目录、子进程启动、超时、日志记录和状态写入。

目标结构建议：

```text
src/web/services/generation_runner.py
src/web/services/job_store.py
```

第一阶段先不强行上 SQLite，可先定义 `JobRecord` 数据结构和文件/内存兼容实现，为第二阶段持久化留接口。

收益：

- `/api/generate` 路由只负责参数校验和调用服务。
- 后续可以自然接入 `job_id`、失败原因、日志片段和状态恢复。

### 5. 拆分 Web 路由

目标：

- 在服务层稳定后，再拆 FastAPI routes，避免把旧的大文件直接切成多个同样耦合的小文件。

目标结构建议：

```text
src/web/
├── app.py
├── routes/
│   ├── articles.py
│   ├── generation.py
│   ├── settings.py
│   └── system.py
└── services/
```

约束：

- `start_web.py` 的启动方式保持兼容。
- 原 API 路径保持兼容。
- 拆分后跑 Web API smoke test。

### 6. 拆分 formatter

目标：

- 在有最小测试和样本输出对照后，再拆 `src/formatter.py`。

推荐顺序：

```text
src/formatting/
├── image_placement.py
├── style_inliner.py
├── markdown_parser.py
├── html_renderer.py
└── preview_page.py
```

约束：

- 先抽纯函数和低副作用逻辑，例如图片位置计算、style 注入。
- 保留 `src/formatter.py` 作为兼容门面，避免一次性改动所有调用方。
- 每一步都用真实或样本文章比较 `article_content.html` 和 `article.html` 的关键结构。

### 7. 抽象 AI client

目标：

- 统一 SiliconFlow 文本生成、选题筛选、生图调用的超时、重试、错误分类和日志格式。

目标结构建议：

```text
src/ai/
├── client.py
├── text_generation.py
├── image_generation.py
└── errors.py
```

约束：

- 不改变 prompt 内容和模型选择逻辑。
- 不读取或改写 `.env`。
- 先做薄封装，再逐步迁移调用点。

## 第一阶段不做

- 不迁移前端框架。
- 不改生产部署配置。
- 不做 Git push、rebase、reset 或发布。
- 不删除历史脚本、截图、日志或 zip 文件；需要清理时先列清单给 Gio 确认。
- 不改变文章生成风格、赛道 prompt 或产品流程。
- 不引入数据库 schema 或数据迁移，除非后续单独确认。

## 阶段完成标准

- Web 文章文件访问路径统一收口，并有最小路径安全测试。
- 生成任务运行逻辑从路由中分离，具备明确状态结构。
- `web_app.py` 的路由、服务、系统动作边界清晰。
- `formatter.py` 至少完成低风险纯函数拆分，并保留兼容入口。
- 验证命令跑通：

```bash
python src/main.py --dry-run --skip-search
```

- 若已引入测试，则同时跑通：

```bash
pytest
```

## 交接提醒

- 每次结构性改造前先写清本次涉及文件、不会触碰的文件和验证方式。
- 涉及 `.env`、部署配置、删除文件、数据库迁移、Git push、rebase、reset、生产发布时，必须先由 Gio 明确确认。
- 修改 `src/formatter.py` 相关逻辑后，必须用文章预览或样本 HTML 检查富文本复制结构。
