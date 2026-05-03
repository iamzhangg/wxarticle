# wxarticle v2

微信公众号文章自动生成工具（赛道制）—— AI写稿 + 自动配图 + 微信排版 + Web控制台

> 🐛 **v2.2** — 本轮加固了 Web 控制台默认监听和文章路径校验，修复每日多篇生成、并发触发、Emoji 误判、Markdown 图片解析等问题，并将正文插图调整为 2 张三等分布局。

## ✨ 功能亮点

- 🏁 **多赛道制**：感悟、人物、生活、AI、高校，每个赛道独立prompt
- 🔍 **每日热门选题**：自动搜索头条/微信热点，AI筛选最佳切入点
- ✍️ **AI生成文章**：Qwen3-235B 写作，卡兹克风格，字数精准
- 🖼 **AI自动配图**：Kolors文生图，封面（2.35:1）+ 2张横向插图（16:9），中文prompt自动翻译英文
- 🎨 **微信精美排版**：紫色系排版，行间距2.2，自动加粗节奏，无底色，复制即用
- 🌐 **Web控制台**：在线浏览、手机预览、一键复制HTML到公众号编辑器
- ⚙️ **可视化设置**：网页端开关赛道、调篇数、改时间，无需改代码
- 📊 **数据持久化**：GitHub data分支存储，跨设备同步

## 🚀 快速开始

### 1. 安装依赖

```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. 配置密钥

```bash
cp .env.example .env
# 编辑 .env，填入你的 API 密钥
```

必填：
- `SILICONFLOW_API_KEY`：硅基流动 API Key（文章生成 + AI生图）

可选：
- `PEXELS_API_KEY` / `PIXABAY_API_KEY`：图库搜索（stock模式）
- `SMMS_TOKEN`：SM.MS图床上传

### 3. 启动Web控制台

```bash
python start_web.py
```

打开 http://localhost:8080 即可使用。Web 控制台默认只监听 `127.0.0.1`；如需局域网或云服务器访问，可显式设置 `HOST=0.0.0.0`，并务必配合登录态、反代鉴权或防火墙限制访问。

### 4. 命令行生成

```bash
# 所有启用的赛道
python src/main.py

# 指定赛道
python src/main.py --track 生活赛道

# 测试模式（不调用API）
python src/main.py --dry-run --skip-search
```

## 🌐 Web控制台功能

| 页面 | 功能 |
|------|------|
| **文章列表** | 按日期浏览所有文章，卡片式展示 |
| **文章预览** | 手机框架预览排版效果，一键复制到微信 |
| **封面下载** | 一键下载微信2.35:1封面图 |
| **赛道设置** | 开关赛道、调整每日篇数 |
| **定时设置** | 修改每天自动生成时间 |
| **生成设置** | 切换图片来源、调整字数范围 |
| **立即生成** | 手动触发指定赛道文章生成 |

## 🎨 微信排版特性

- **紫色系风格**：标题、加粗、链接统一紫色（#7c3aed）
- **行间距2.2**：阅读舒适，视觉透气
- **自动加粗节奏**：AI生成时自动在关键短语加粗，每段1-2处
- **零底色**：所有文字元素无background，复制到微信编辑器不带入任何颜色底色
- **微信兼容**：不用::after、border-image、background-clip等不兼容属性
- **图片base64内嵌**：复制到微信时图片自动上传，不依赖外部图床
- **2张横向插图**：16:9比例，分别靠近正文 1/3、2/3 位置，将文章自然分成三段
- **首字下沉**：文章首段首字放大紫色，增加视觉层次
- **装饰分割线**：SVG内联分割线，微信兼容

## 📁 项目结构

```
wxarticle/
├── AGENTS.md                # Codex 项目指引
├── CLAUDE.md                # Claude Code 项目指引
├── config.yaml              # 赛道+生成+定时配置（网页可编辑）
├── .env                     # API密钥（不进版本控制）
├── start_web.py             # 启动Web控制台
├── requirements.txt
├── assets/
│   └── guides/              # 引导图（开头关注+结尾点赞在看）
├── tracks/                  # 赛道目录
│   ├── 感悟赛道/
│   │   └── prompt.md        # 写作约束
│   ├── 人物赛道/
│   ├── 生活赛道/
│   ├── AI赛道/
│   └── 高校赛道/
├── src/
│   ├── main.py              # 主流程：赛道制文章生成
│   ├── web_app.py           # Web控制台（FastAPI）
│   ├── track_manager.py     # 赛道管理
│   ├── topic_searcher.py    # 热门选题搜索
│   ├── article_generator.py # AI文章生成（卡兹克风格）
│   ├── formatter.py         # 微信HTML排版（零底色）
│   ├── image_generator.py   # AI生图（Kolors，16:9横向插图）
│   ├── image_searcher.py    # 图库搜索配图
│   ├── image_uploader.py    # SM.MS图床上传
│   ├── data_sync.py         # GitHub data分支数据同步
│   ├── config.py            # 配置加载（.env > yaml > 默认值）
│   └── web/
│       └── static/
│           └── index.html   # 前端SPA
└── .github/workflows/
    └── daily.yml            # GitHub Actions 定时任务
```

## 🔧 赛道配置

编辑 `config.yaml` 或通过Web控制台设置：

```yaml
tracks:
  - name: 生活赛道
    enabled: true             # 是否启用
    articles_per_day: 1       # 每日篇数
    keywords: ["生活小窍门", "家居技巧", "收纳整理"]
    search_sources: ["toutiao", "weixin"]

generation:
  image_source: ai            # stock=图库 / ai=AI生图 / auto=自动
  inline_image_count: 2       # 正文插图数量，默认两张图三等分正文
  word_count_min: 1200        # 最少字数
  word_count_max: 1300        # 最多字数
```

### 自定义写作风格

1. 编辑 `tracks/{赛道名}/prompt.md`，写入你的写作约束
2. AI会结合卡兹克写作风格 + 赛道约束来生成文章
3. 赛道约束优先级 > 风格指南

## 🖼 图片生成配置

| 图片类型 | 尺寸 | 比例 | 说明 |
|----------|------|------|------|
| 封面图 | 900×383 | 2.35:1 | 微信公众号封面比例 |
| 插图 | 1024×576 | 16:9 | 横向长方形，正文配图 |
| 引导图 | 原图裁剪 | - | 开头关注+结尾点赞在看 |

- 图片生成模型：Kwai-Kolors/Kolors（硅基流动）
- 中文prompt自动翻译英文（Qwen3-8B），避免中文乱码
- negative_prompt自动排除文字/水印
- 正文插图默认生成 2 张，排版时尽量放在正文约 1/3 和 2/3 处

## 🤖 GitHub Actions 部署

1. 推送代码到GitHub
2. 在 Settings → Secrets 添加：
   - `SILICONFLOW_API_KEY`
   - `PEXELS_API_KEY`（可选）
   - `SMMS_TOKEN`（可选）
3. 每天08:00自动生成，输出自动提交到data分支
4. 也支持手动触发（Actions页面 → Run workflow）

## 🖥 Windows 宝塔部署

服务器使用管理员 PowerShell 执行：

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/iamzhangg/wxarticle/master/deploy_windows.ps1 | iex
```

脚本会从 GitHub 拉取 `master` 到 `C:\wxarticle`，创建虚拟环境、安装依赖，并注册开机自启任务 `wxarticle`。服务默认只监听 `127.0.0.1:8080`；公网访问建议在宝塔/Nginx 中反向代理到 `http://127.0.0.1:8080`，并加访问认证或防火墙白名单。

首次部署后编辑：

```text
C:\wxarticle\.env
```

至少填入：

```env
SILICONFLOW_API_KEY=你的硅基流动Key
IMAGE_SOURCE=ai
```

然后重启任务：

```powershell
schtasks /run /tn wxarticle
```

## 🧩 涉及的模型

| 用途 | 模型 | 平台 |
|------|------|------|
| 文章写作 | Qwen3-235B | 硅基流动 |
| prompt翻译 | Qwen3-8B | 硅基流动 |
| 封面图/插图 | Kwai-Kolors/Kolors | 硅基流动 |
| 图库搜索 | Pexels/Pixabay API | 免费 |

## 📝 使用流程

1. **配置赛道** → Web控制台或config.yaml
2. **每天8点** → GitHub Actions自动生成（或手动点击"立即生成"）
3. **打开Web控制台** → 浏览今日文章
4. **手机预览** → 确认排版效果
5. **复制HTML** → 一键复制，粘贴到公众号编辑器
6. **上传封面** → 下载封面图，上传到公众号后台
7. **发布** 🎉

## ⚠️ 微信复制注意事项

- 复制HTML时，图片已base64内嵌，粘贴后微信会自动上传到服务器
- 所有文字元素无底色，不会带入任何背景颜色
- 封面图不包含在正文中，需单独上传到公众号后台
- 正文包含2张横向插图 + 首尾引导图
