# TeleGrabber

TeleGrabber 是一个 Telegram 机器人，用于自动保存接收到的图片、视频、GIF 动画和通用文件，并自带 Web 可视化管理后台。

## 功能特点

- **多类型媒体自动下载**：图片、视频、GIF 动画、文档类图片、通用文件（压缩包/APK/PDF 等）
- **异步架构**：基于 python-telegram-bot v21（asyncio），支持并发处理消息，大文件下载不阻塞其他操作
- **混合下载模式**：
  - 小文件 (<20MB) 通过标准 Bot API 下载，速度极快
  - 大文件 (>=20MB) 自动切换至 MTProto (User API) 协议
  - 进度条实时显示百分比，并用不同 emoji 区分通道：Bot API（⏳/✅/❌）、User API（🕓/🟢/🔴）
- **下载前信息展示**：每次下载前显示检测到的媒体类型、大小和下载通道，结果消息也保留该信息
- **消息链接下载**：支持 `/link` 命令和自动识别文本中的 `t.me` 链接，通过 User API 下载私密频道/禁止转发消息中的媒体
- **通用文件下载白名单**：通过 `ALLOWED_FILE_EXTENSIONS` 配置允许下载的文件扩展名（默认支持 zip/rar/7z/apk/pdf 等），非图片/视频文档根据白名单决定是否下载
- **SQLite 数据库**：持久化存储所有媒体元数据，支持全局去重与跨会话追踪
- **审计日志**：调试时可通过 `AUDIT_LOG=true` 开启，收到的消息会按来源类型写入 `data/audit_{channel,bot,group,private,other}.json`；默认关闭
- **智能去重与安全删除**：自动跳过库中已存在的资源；"删除"操作仅撤销本次下载，绝不触及历史存量数据
- **单条 / 媒体组操作按钮**：下载完成后提供重新下载、强制重下、删除等即时操作；重新下载时保留信息头
- **Web 管理后台**：内置基于 FastAPI 的可视化管理终端，支持大图/视频预览、媒体组聚合展示与远程一键删除（个人本地使用，不启用应用内登录）
- **统一存储库**：按来源归类保存，不做日期分层，方便管理和搜索
- **用户访问限制**：支持白名单机制，仅允许指定用户使用机器人
- **代理支持**：内置 SOCKS5/HTTP 代理支持，适应不同网络环境

## 项目结构

```
TeleGrabber/
│
├── main.py                # 主程序入口
├── config.py              # 配置管理（含白名单、审计开关）
├── utils.py               # 数据库、文件检测、审计日志
├── user_api.py            # MTProto (User API) 下载引擎
├── web_backend.py         # Web 后端服务 (FastAPI)
├── api_response.py        # 统一响应/错误码/requestId
├── web/                   # Vue 3 前端（构建产物 web/dist，已忽略）
├── fix_metadata.py         # 元数据修复脚本（message_time / message_id / source_link1 / source_username）
├── bot/                   # 机器人逻辑 (python-telegram-bot v21, async)
│   ├── handlers.py        # 消息处理器
│   ├── download.py        # 下载逻辑（含进度回调）
│   ├── media_group.py     # 媒体组收集与并发下载
│   ├── callbacks.py       # 按钮回调处理
│   ├── helpers.py         # 装饰器、转发溯源
│   ├── errors.py          # 全局错误处理
│   └── state.py           # 全局共享状态
├── conf/
│   ├── config.toml        # 实际配置（含敏感信息，已忽略）
│   └── config.example.toml # 配置模板
├── data/
│   ├── telegrabber.db     # SQLite 数据库
│   └── audit_*.json       # 审计日志（按来源类型拆分）
├── requirements.txt       # 依赖列表
└── downloads/             # 媒体文件保存目录
```

## 安装方法

### 标准安装

1. 克隆此仓库：

```bash
git clone https://github.com/yourusername/telegrabber.git
cd telegrabber
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 构建前端：

```bash
cd web
npm install
npm run build
cd ..
```

> Docker 部署会在镜像构建阶段自动完成前端构建，无需手动执行。

4. 创建配置文件：

```bash
cp conf/config.example.toml conf/config.toml
nano conf/config.toml  # 或者使用你喜欢的文本编辑器
```

### Docker 部署

TeleGrabber 也支持使用 Docker 进行部署，这是最简单、最推荐的部署方式：

1. 克隆此仓库：

```bash
git clone https://github.com/yourusername/telegrabber.git
cd telegrabber
```

2. 创建并配置 `conf/config.toml`：

```bash
cp conf/config.example.toml conf/config.toml
nano conf/config.toml
```

3. 使用 Docker Compose 启动服务：

```bash
docker-compose up -d
```

4. 查看日志：

```bash
docker-compose logs -f
```

5. 停止服务：

```bash
docker-compose down
```

Docker 部署的优点：

- 无需手动安装 Python 和依赖
- 镜像内置 ffmpeg，支持视频封面生成与视频尺寸探测
- 环境隔离，不会影响系统环境
- 自动重启服务
- 数据持久化存储在宿主机的 downloads 目录

注意：首次部署会自动构建镜像，这可能需要几分钟。下载的媒体文件将保存在宿主机的 `downloads` 目录中。

## 如何获取 Telegram 机器人令牌

1. 在 Telegram 中搜索 [@BotFather](https://t.me/BotFather)
2. 发送命令 `/newbot` 并按照提示创建一个新机器人
3. 完成后，BotFather 会提供一个令牌（格式类似 `123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ`）
4. 将此令牌填入 `conf/config.toml` 的 `[telegram]` 节：`bot_token = "..."`

## 网络问题解决方案

如果你在中国大陆或其他网络受限区域，可能无法直接连接到 Telegram API。可以在 `conf/config.toml` 的 `[telegram]` 节设置代理:

```toml
[telegram]
# 使用 SOCKS5 代理
proxy_url = "socks5h://127.0.0.1:1080"

# 或者使用 HTTP 代理
# proxy_url = "http://127.0.0.1:8124"
```

SOCKS 代理支持已包含在 `requirements.txt`（`python-telegram-bot[socks]` 提供 Bot API 侧支持，`pysocks` 提供 User API 侧支持），按上述步骤安装依赖即可，无需额外操作。

## 使用方法

运行机器人：

```bash
python main.py
```

机器人启动后，你可以向它发送以下内容：

### 单条消息

- **单张图片 / 视频 / GIF**：机器人将显示检测到的类型、大小和下载通道，然后下载保存，最后反馈结果
- **文档类图片**：以"文件"方式发送的图片（非直接相册发送），会自动检测文件头确认是图片格式后保存
- **通用文件**：压缩包 (.zip/.rar/.7z)、APK、PDF 等非图片/视频文档，根据 `ALLOWED_FILE_EXTENSIONS` 白名单决定是否下载
- **文本消息**：自动识别消息中的 `t.me` 链接并触发 `/link` 下载流程

### 命令

- `/start` - 启动机器人并收到欢迎消息
- `/help` - 获取帮助信息
- `/stats` - 查看媒体库统计（总数、今日新增、按类型分布、来源 Top5）
- `/link <消息链接>` - 通过 User API 下载账号可访问消息中的媒体，例如 `/link https://t.me/channel/123`
- `/link <username|chat_id> <消息ID>` - 不输入完整链接也可定位消息，例如 `/link channel 123` 或 `/link -1001234567890 123`

> `/link` 命令和自动链接识别使用 User API (MTProto) 下载媒体，可以获取到被禁止复制/下载/转发的受保护频道中的内容。

### 信息展示格式

所有下载操作会在消息中统一展示检测到的媒体信息：

```
📋 检测到单张图片
大小: 115.9KB
通道: Bot API

⏳ 正在保存...
```

完成后：

```
📋 检测到单张图片
大小: 115.9KB
通道: Bot API

✅ 图片已保存
```

下载进度更新时，该信息头保持不动，仅更新状态行。

## 媒体组处理机制

当用户发送多张图片或视频（媒体组/相册）时：

1. 机器人会先发送状态消息：
   - 如果是第一个媒体组，显示"正在收集媒体组内容，请稍候..."
   - 如果已有其他媒体组在处理或排队中，显示"媒体组已加入队列，请稍候..."
2. 系统会在后台收集所有属于同一媒体组的图片和视频（默认等待 2 秒钟）
3. 收集完成后，显示媒体组概览（项目数、图片/视频数量、各项日下载通道），然后在原消息上实时更新进度
4. 所有媒体保存完毕后，显示完成状态、用时和详细结果（含重复项提示）

```
📁 检测到媒体组 (5项)
🖼️ 图片: 3张
🎬 视频: 2个
☁️ 第1、3、5项通过 User API 下载

正在保存媒体组...
进度: ⏳⏳⏳⏳⏳ (0/5)
```

### 下载通道图标区分

进度条 emoji 区分 Bot API 和 User API 通道：

| 状态 | Bot API | User API |
|------|---------|----------|
| 等待 | ⏳ | 🕓 |
| 下载中 | 🔽X% | ☁️X% |
| 完成 | ✅ | 🟢 |
| 失败 | ❌ | 🔴 |
| 重复 (跳过) | ♻️ | ♻️ |

这一眼即可看出每项实际走哪种下载方式。

## User API 下载范围与 20MB 限制

User API（MTProto）使用的是 `TELEGRAM_API_ID/HASH` 对应账号的登录会话，因此它只能访问**该账号自己能看到的会话**，与媒体是谁发送的无关。

| 场景 | User API 能否下载 |
|------|-------------------|
| User API 账号自己与 bot 的私聊 | 可以 |
| 其他用户与 bot 的私聊 | 不可以 |
| User API 账号已加入的群组 / 频道 | 可以，不限发送者 |
| User API 账号未加入的私密群组 / 频道 | 不可以 |
| 公开频道 | 通常可以 |

下载通道的边界：

- **Bot API**：可以下载任意允许用户发给 bot 的文件，但云端 Bot API 上限为 **20MB**
- **User API**：没有 20MB 限制，但受账号会话访问范围限制
- 因此，**其他用户私聊中超过 20MB 的文件，当前架构无法下载**：
  - Bot API 超过 20MB 下不了
  - User API 又看不到其他用户的私聊

典型表现是媒体组里图片（<20MB，走 Bot API）成功，而某个视频或大文件（走 User API）失败，并提示 `User API 下载失败`。日志里会出现目标消息 `Media: None`、在最近历史中找不到匹配媒体，这是因为 User API 读到的是它自己账号的会话，不是请求者与 bot 的私聊。

如果需要支持“其他用户私聊中的大文件”，推荐部署 **本地 Bot API server**（`telegram-bot-api`），将下载上限从 20MB 提升到 **2GB**（使用 `conf/config.toml` 中已配置的 `TELEGRAM_API_ID/HASH`）：

```python
ApplicationBuilder()
    .base_url("http://127.0.0.1:8081/bot")
    .local_mode(True)
```

也可以把 User API 账号加入对应的群组/频道，让群组/频道场景走 User API；但私聊场景无法通过加群解决。

# 🤖 Telegram 机器人交互界面

### 媒体组（相册）按钮

在通过机器人下载媒体组（相册）时，TeleGrabber 提供了一套便捷的交互按钮，方便您对任务进行即时控制：

- **♻️ 重新下载本次**：安全重试模式。仅清理并重新下载本次任务产生的新文件，**不会影响**库中已存在的重复资源。
- **🔥 强制重下全部**：全量强制模式。彻底从数据库和磁盘中抹除该媒体组的所有历史记录（含存量重复项），然后进行真正的全量重新下载。
- **❌ 重试失败项**：如果下载过程中部分文件因网络原因报错，点击此按钮将仅重试那些失败的项目。
- **🔄 刷新状态**：实时同步最新的处理进度，支持在删除后通过按钮快速恢复下载。
- **🗑️ 删除本次内容**：一键撤销。仅从本地磁盘和数据库中移除本次下载的物理文件和元数据，确保存量数据的安全性。

### 单条消息按钮

发送单张图片/视频/动画/文档时，下载结果消息也带有操作按钮（行为与媒体组保持一致）：

- **成功 / 失败**：♻️ 重新下载、🗑️ 删除本次内容
- **检测到重复**：🔥 强制重下（覆盖库中已存在的同一资源）
- 删除后会保留 ♻️ 重新下载按钮，方便删了再下回来；重新下载在原消息上原地更新进度与结果，并保留信息头。

# [NEW] Web 可视化管理后台

TeleGrabber 现在自带一个功能强大的 Web 管理终端，随机器人同步启动。

### 主要功能：

- **Premium UI**：现代深色系毛玻璃设计，支持自适应布局，自带专属 **Robot Favicon** 图标。
- **媒体组聚合**：自动按 `media_group_id` 进行分组展示，并提取代表性标题。
- **智能排序**：组内媒体按文件名自然排序（1, 2, ..., 10），符合人类预览习惯。
- **播放与删除**：直接在浏览器内预览图片、播放视频（支持强效停音逻辑），删除采用局部刷新（不回到顶部），并通过玻璃拟态确认弹窗二次确认。
- **筛选计数**：按来源/搜索筛选时，顶部数量会显示"找到 N 条"。
- **直接操作**：删除、重试、标签等操作无需登录；Web 后台默认只监听本机，请勿直接暴露到公网。
- **一键追溯**：预览页提供原始 Telegram 来源链接，支持一键跳转回原始频道/聊天。
- **下载任务中心**：侧栏「下载任务」查看排队/下载中/暂停/成功/失败/已取消、实时进度、失败原因；支持按来源/媒体组筛选，失败任务单条或批量重试、优先重试、暂停/继续重试队列、取消排队任务、任务详情抽屉与分页加载，任务持久化在 SQLite。重试优先走 User API，小文件失败时自动回退 Bot API；媒体组失败项重试后会回到原相册。
- **存储管理**：侧栏「存储管理」查看总占用、按来源/类型统计、磁盘使用情况与只读的重复文件列表。
- **系统状态**：侧栏「系统状态」查看 Bot、User API、代理、磁盘与运行检查清单。
- **全文搜索**：基于 SQLite FTS5（trigram）检索文案/文件名/来源，支持多关键词、搜索历史与筛选条件 chips。
- **来源管理**：可置顶、隐藏来源，设置备注名；显示最近同步时间、禁止转发标记与该来源失败任务数，并可直接重试该来源失败任务。
- **媒体管理**：收藏、标签、备注；支持按收藏/标签筛选，重复文件只读查看。
- **媒体查看器**：键盘切换、空格播放/暂停、复制链接、视频续播；文件直接在项目机器的 `downloads/` 目录取用。
- **筛选增强**：消息流顶部漏斗按钮支持按媒体类型、日期范围、收藏、标签筛选，和搜索/来源筛选可叠加使用。
- **大列表优化**：媒体分页改为 keyset 游标，消息流使用虚拟滚动，只渲染视口附近的气泡。
- **运维能力**：`/healthz` 健康检查、磁盘不足横幅；审计日志开启后可直接查看 `data/audit_*.json`。
- **本地访问**：根路径直接进入消息流，无登录页；默认仅监听 `127.0.0.1`。

### 访问方式：

默认访问地址：`http://127.0.0.1:5005`

Web 后台默认只监听本机，且没有内置登录鉴权。请勿将端口直接暴露到公网；如需从其他设备访问，建议使用 Tailscale、WireGuard、SSH 隧道，或在反向代理上配置 IP 白名单/Basic Auth。

### 地址与端口配置：

```toml
[web]
host = "127.0.0.1"  # 默认仅本机；确需局域网/容器访问时再改为 "0.0.0.0"
port = 5005
```

> **无内置鉴权说明**：去掉登录后，任何能访问该端口的人都可以查看、删除媒体，并读取审计日志。修改 `host = "0.0.0.0"` 前请确认网络环境可信。
>
> **任务中心配置**：
> ```toml
> [tasks]
> retain_days = 30      # 终态任务保留天数
> retry_concurrency = 2 # 重试并发数
> min_free_mb = 512     # 下载前最小剩余磁盘空间
> ```

## 配置选项

完整配置见 `conf/config.example.toml`，当前支持：

```toml
[telegram]
# 必填：Telegram 机器人令牌
bot_token = "your_token_here"

# 选填：MTProto (User API) 凭据（用于下载 > 20MB 文件和 /link 消息链接）
# 获取地址：https://my.telegram.org
api_id = 0
api_hash = ""

# 可选：代理设置
proxy_url = "http://127.0.0.1:8123"

# 连接超时（秒）与下载重试次数
connection_timeout = 30
download_retries = 3
# 单次下载总超时（秒）
download_timeout = 3600
# 连续无进度判定卡死（秒）
download_stall_timeout = 180

# 可选：允许使用机器人的用户名或用户 ID
allowed_users = ["your_username", "123456789"]

# 可选：允许下载的文件扩展名白名单
allowed_file_extensions = [".zip", ".rar", ".7z", ".apk", ".pdf"]

[storage]
# 可选：保存目录（默认为 downloads）
save_dir = "downloads"
# 运行数据目录（SQLite、session、审计日志、缩略图）
data_dir = "data"

[web]
# 监听地址（默认仅本机）与端口
host = "127.0.0.1"
port = 5000

[audit]
# 可选：审计日志开关（默认关闭）
enabled = false
```

## 用户访问限制

TeleGrabber 支持限制只有特定用户才能使用机器人的功能，这对于在个人服务器上部署的实例特别有用。

### 设置方法：

1. 在 `conf/config.toml` 的 `[telegram]` 节配置 `allowed_users`
2. 填入允许使用的 Telegram 用户名或用户 ID
3. 用户 ID 可以通过与[@userinfobot](https://t.me/userinfobot)对话获取

示例：

```toml
[telegram]
allowed_users = ["john_doe", "jane_smith", "123456789"]
```

### 行为说明：

- 当非授权用户尝试使用机器人时，会收到访问受限的提示信息
- 提示信息中会包含项目的 GitHub 地址，引导用户部署自己的实例
- 所有授权验证失败的尝试都会在日志中记录

如果 `[telegram] allowed_users` 为空或未设置，机器人将允许所有用户使用。

## 高级配置

如果你想调整媒体组收集的等待时间（默认为 2 秒），可以在`bot/state.py`中修改：

```python
# 修改这个值可以调整收集媒体组的等待时间（秒）
MEDIA_GROUP_COLLECT_TIME = 2
```

- 增加这个值可以确保在慢速网络下收集完整媒体组
- 减少这个值可以加快处理速度，但可能在某些情况下漏掉图片

## 文件夹组织结构

TeleGrabber 采用"统一媒体库"方式按来源归类保存（不做日期分层，避免散乱）：

```
downloads/
│
├── direct_messages/     # 来自个人 / 私聊 / 未知转发的媒体
│   └── 用户名(或来源)/
│       └── [媒体文件]
│
└── 频道名称 / 群组名称/  # 来自频道、群组的媒体，直接以来源名作为目录
    └── [媒体文件]
```

> 说明：全局统一的 SQLite 数据库位于 `data/telegrabber.db`；媒体文件按来源分类组织，所有元数据均存储在数据库中。

## 视频格式支持

TeleGrabber 支持多种常见的视频格式，包括：

- MP4 (.mp4)
- WebM (.webm)
- QuickTime (.mov)
- AVI (.avi)

系统会自动检测视频的实际格式，如果无法确定，将默认使用 .mp4 扩展名。

## 文件命名规则

TeleGrabber 使用基于毫秒时间戳的命名方案，保证唯一性：

- 媒体组图片/视频：`{完整媒体组ID}_{序号}_{时间戳}{扩展名}`
  例如：`13991698976443269_1_1686834561723.jpg` 或 `.mp4`
- 单张图片 / 单个视频 / GIF 动画 / 文档图片：`single_{时间戳}{扩展名}`
  例如：`single_1686834561723.jpg`、`single_1686834561723.mp4`、`single_1686834561723.gif`

时间戳为毫秒级数字格式（13 位数字），如`1686834561723`，确保在短时间内连续保存的媒体文件也能有唯一文件名。

系统会自动检测每个媒体文件的实际格式（通过文件头魔数判断），并使用正确的扩展名（如 .jpg、.png、.gif、.webp、.mp4、.avi 等）。

## 支持的媒体类型

TeleGrabber 支持以下类型的媒体：

### 图片格式

- JPEG (.jpg)
- PNG (.png)
- GIF (静态, .gif)
- WebP (.webp)
- BMP (.bmp)
- 其他常见图片格式

### 视频格式

- MP4 (.mp4)
- WebM (.webm)
- QuickTime (.mov)
- AVI (.avi)

### 动画格式

- GIF 动画 (.gif)
- 基于 MP4 的动画 (Telegram 有时将 GIF 作为无声 MP4 发送)

### 通用文件（需在白名单内）

- ZIP (.zip)
- RAR (.rar)
- 7z (.7z)
- APK (.apk)
- PDF (.pdf)
- 以及通过 `ALLOWED_FILE_EXTENSIONS` 配置的其他扩展名

**重要提示**：
- **小文件 (<20MB)**：通过标准 Bot API 下载，速度极快且无需额外配置。
- **大文件 (>=20MB)**：系统自动切换至 **MTProto (User API)** 协议。
- **初次启动**：若配置了 `API_ID`，首次运行需要在终端输入手机号和验证码以完成登录。登录后的 session 文件将加密存储在本地。
- **文件检测**：通过文件头魔数检测真实类型（`get_archive_ext`），确保文件扩展名与内容一致。

### 元数据管理

所有媒体文件的详细信息都保存在 SQLite 数据库 `data/telegrabber.db` 中，包括：

- 文件名
- 保存时间
- Telegram 文件 ID
- Telegram 文件唯一 ID
- 媒体组 ID (如适用)
- 媒体类型 (photo、video、animation、document 等)
- 来源名称 (频道标题、群组名、bot 显示名等)
- 来源 ID (频道 ID、用户 ID 等)
- 来源用户名 (Telegram 用户名，如 `sifangktv10`)
- 来源链接1 (优先用户名格式，如 `https://t.me/username/msg_id`)
- 来源链接2 (数字 ID 格式，如 `https://t.me/c/id/msg_id`)
- 来源类型 (channel、group、bot、user、private_user 等)

所有元数据仅存储在 SQLite 数据库中，无额外物理备份。

## 审计日志

所有机器人接收到的消息都会按来源类型写入 `data/audit_{channel,bot,group,private,other}.json`（JSON 数组格式），每条记录包含：

- 接收时间
- 消息类型（photo / video / animation / document / media_group / text / link）
- 完整的原始消息数据（`message.to_dict()`）
- 来源信息（chat_id、user_id、source 等）
- 当前会话消息 ID、原始来源消息 ID、消息时间、备注信息

审计日志默认关闭；调试时可通过 `conf/config.toml` 的 `[audit] enabled = true` 临时开启。

## 许可证

本项目采用 MIT 许可证。详细信息请参阅 [LICENSE](LICENSE) 文件。
