# wxarticle v2

文章生成、排版与发布推送自动化工具。项目提供赛道化选题、AI 写稿、自动配图、内容排版、浏览预览和一键复制能力，适合搭建自己的内容生产工作流。

## 功能亮点

- 多赛道创作：为不同内容方向维护独立 prompt、关键词和生成数量。
- 热点选题辅助：按赛道关键词搜索热门话题，并用 AI 筛选切入角度。
- AI 文章生成：调用硅基流动模型生成指定字数范围的文章。
- 自动配图：支持 AI 生图，也可切换图库搜索模式。
- 内容排版：生成适合富文本编辑器粘贴的 HTML，内嵌图片并去除多余底色。
- Web 控制台：浏览文章、预览排版、复制 HTML、下载封面、调整配置。
- 定时与手动生成：支持每天定时生成，也支持在 Web 控制台立即生成。

## 快速开始

### 1. 安装依赖

```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

macOS / Linux 可使用：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置密钥

复制示例配置：

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```env
SILICONFLOW_API_KEY=你的硅基流动Key
IMAGE_SOURCE=ai
```

可选：

```env
PEXELS_API_KEY=
PIXABAY_API_KEY=
SMMS_TOKEN=
```

### 3. 启动 Web 控制台

```bash
python start_web.py
```

打开：

```text
http://localhost:8080
```

默认只监听 `127.0.0.1`。如果部署到服务器并需要公网访问，请放在反向代理、登录认证或防火墙白名单后面。

### 4. 命令行生成

```bash
# 运行所有启用赛道
python src/main.py

# 指定赛道
python src/main.py --track 生活赛道

# 测试流程，不调用外部 API
python src/main.py --dry-run --skip-search
```

## Web 控制台

| 页面 | 功能 |
| --- | --- |
| 文章列表 | 按日期浏览已生成文章 |
| 文章预览 | 手机框架预览排版效果 |
| 一键复制 | 复制富文本 HTML 到编辑器 |
| 封面下载 | 下载 2.35:1 封面图 |
| 赛道设置 | 开关赛道、调整每日篇数 |
| 定时设置 | 修改每天自动生成时间 |
| 生成设置 | 切换图片来源、调整字数范围 |
| 立即生成 | 手动触发指定赛道生成 |

## 内容排版

- 适合富文本编辑器粘贴的 HTML 片段。
- 所有文字元素注入 `background:none`，减少粘贴时带入底色。
- 图片以 base64 内嵌，复制时无需依赖外部图床。
- 默认正文插入 2 张横向配图，位置靠近文章 1/3 和 2/3。
- 生成完整预览页和纯内容片段，便于检查和发布。

## 赛道配置

可以通过 Web 控制台修改，也可以直接编辑 `config.yaml`：

```yaml
tracks:
  - name: 生活赛道
    enabled: true
    articles_per_day: 1
    keywords: ["生活小窍门", "家居技巧", "收纳整理"]
    search_sources: ["toutiao"]

generation:
  image_source: ai
  inline_image_count: 2
  word_count_min: 1200
  word_count_max: 1300
```

每个赛道的写作约束位于：

```text
tracks/{赛道名}/prompt.md
```

## 输出结构

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

## 常用配置

| 配置 | 说明 |
| --- | --- |
| `SILICONFLOW_API_KEY` | 硅基流动 API Key |
| `IMAGE_SOURCE` | `ai` / `stock` / `auto` |
| `MODEL_NAME` | 文章生成模型 |
| `PEXELS_API_KEY` | 图库搜索，可选 |
| `PIXABAY_API_KEY` | 图库搜索，可选 |
| `SMMS_TOKEN` | 图床上传，可选 |

## 部署

本项目可以本地运行，也可以部署到任意支持 Python 的服务器。Windows Server、计划任务、反向代理和 GitHub Actions 等可选部署方式见：

[docs/deployment.md](docs/deployment.md)

## 安全提醒

- 不要提交 `.env`，公开项目只保留 `.env.example`。
- Web 控制台包含生成、配置、更新和删除能力，公网部署时必须加访问保护。
- 默认监听 `127.0.0.1` 是为了避免控制台被直接暴露。

## License

MIT
