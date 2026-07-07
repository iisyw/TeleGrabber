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
- **审计日志**：所有接收到的消息（含单条媒体、文本、媒体组）原始数据自动写入 `data/audit.jsonl`，便于回溯审查（可通过 `AUDIT_LOG=false` 关闭）
- **智能去重与安全删除**：自动跳过库中已存在的资源；"删除"操作仅撤销本次下载，绝不触及历史存量数据
- **单条 / 媒体组操作按钮**：下载完成后提供重新下载、强制重下、删除等即时操作；重新下载时保留信息头
- **Web 管理后台**：内置基于 FastAPI 的可视化管理终端，支持大图/视频预览、媒体组聚合展示与远程一键删除（含 Basic Auth 鉴权）
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
├── bot/                   # 机器人逻辑 (python-telegram-bot v21, async)
│   ├── handlers.py        # 照片/视频/文档/动画/通用文件处理器
│   ├── download.py        # 单条消息下载公共逻辑（含进度回调）
│   ├── media_group.py     # 媒体组收集与并发下载
│   ├── callbacks.py       # 按钮回调处理
│   ├── helpers.py         # 装饰器、转发溯源等
│   └── state.py           # 全局共享状态
├── static/                # Web 前端静态资源 (HTML/CSS/JS)
├── data/
│   ├── .env.example       # 环境变量模板
│   └── audit.jsonl        # 审计日志（原始消息数据）
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

3. 创建配置文件：

```bash
# 复制配置模板到 data/ 目录
cp data/.env.example data/.env

# 编辑配置文件，填入你的Telegram机器人令牌
nano data/.env  # 或者使用你喜欢的文本编辑器
```

### Docker 部署

TeleGrabber 也支持使用 Docker 进行部署，这是最简单、最推荐的部署方式：

1. 克隆此仓库：

```bash
git clone https://github.com/yourusername/telegrabber.git
cd telegrabber
```

2. 创建并配置 .env 文件：

```bash
# 复制配置模板到 data/ 目录
cp data/.env.example data/.env

# 编辑配置文件
nano data/.env
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
- 环境隔离，不会影响系统环境
- 自动重启服务
- 数据持久化存储在宿主机的 downloads 目录

注意：首次部署会自动构建镜像，这可能需要几分钟。下载的媒体文件将保存在宿主机的 `downloads` 目录中。

## 如何获取 Telegram 机器人令牌

1. 在 Telegram 中搜索 [@BotFather](https://t.me/BotFather)
2. 发送命令 `/newbot` 并按照提示创建一个新机器人
3. 完成后，BotFather 会提供一个令牌（格式类似 `123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ`）
4. 将此令牌复制到 `.env` 文件中的 `TELEGRAM_BOT_TOKEN=` 后面

## 网络问题解决方案

如果你在中国大陆或其他网络受限区域，可能无法直接连接到 Telegram API。你可以通过在`.env`文件中设置代理来解决:

```
# 使用SOCKS5代理
PROXY_URL=socks5h://127.0.0.1:1080

# 或者使用HTTP代理
# PROXY_URL=http://127.0.0.1:8124
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
- **安全删除**：删除等写操作受 HTTP Basic Auth 保护（见下方配置）。
- **一键追溯**：预览页提供原始 Telegram 来源链接，支持一键跳转回原始频道/聊天。

### 访问方式：

默认访问地址：`http://localhost:5000` (或服务器 IP:5000)

### 端口配置：

如需修改 Web 服务端口，可以在 `data/.env` 文件中设置：
```bash
WEB_PORT=5000  # 默认 5000
```

> **Web 后台登录鉴权**：删除等写操作接口受 HTTP Basic Auth 保护，凭据通过以下两个环境变量配置：
> ```bash
> WEB_USERNAME=admin   # 登录用户名，默认 admin
> WEB_PASSWORD=        # 登录密码，留空则禁用所有写操作（删除接口失效）
> ```
> 注意：Basic Auth 在明文 HTTP 上传输，仅适合内网使用；公网访问请在前面套 HTTPS 反向代理。

## 配置选项

在`data/.env`文件中可设置以下选项：

```
# 必填：Telegram 机器人令牌
TELEGRAM_BOT_TOKEN=your_token_here

# 选填：MTProto (User API) 凭据 (用于下载 > 20MB 文件和 /link 消息链接)
# 获取地址：https://my.telegram.org
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# 可选：Web 后台登录凭据
WEB_USERNAME=admin
WEB_PASSWORD=your_password

# 可选：代理设置
PROXY_URL=http://127.0.0.1:8123

# 可选：保存目录（默认为 ./downloads）
SAVE_DIR=./downloads

# 可选：允许使用机器人的用户列表
ALLOWED_USERS=your_username,123456789

# 可选：允许下载的文件扩展名白名单（逗号分隔）
# ALLOWED_FILE_EXTENSIONS=.zip,.rar,.7z,.apk,.tar,.gz,.tgz,.pdf,.doc,.docx,.xls,.xlsx,.exe,.iso

# 可选：审计日志开关（默认关闭）
# AUDIT_LOG=false
```

## 用户访问限制

TeleGrabber 支持限制只有特定用户才能使用机器人的功能，这对于在个人服务器上部署的实例特别有用。

### 设置方法：

1. 在`.env`文件中添加`ALLOWED_USERS`环境变量
2. 填入允许使用的 Telegram 用户名或用户 ID，多个用户用逗号分隔
3. 用户 ID 可以通过与[@userinfobot](https://t.me/userinfobot)对话获取

示例：

```
ALLOWED_USERS=john_doe,jane_smith,123456789
```

### 行为说明：

- 当非授权用户尝试使用机器人时，会收到访问受限的提示信息
- 提示信息中会包含项目的 GitHub 地址，引导用户部署自己的实例
- 所有授权验证失败的尝试都会在日志中记录

如果`ALLOWED_USERS`环境变量为空或未设置，机器人将允许所有用户使用。

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
├── unsorted/            # 无法识别来源的媒体
│   ├── metadata.csv
│   └── [媒体文件]
│
├── direct_messages/     # 来自个人 / 私聊 / 未知转发的媒体
│   └── 用户名(或来源)/
│       ├── metadata.csv
│       └── [媒体文件]
│
└── 频道名称 / 群组名称/  # 来自频道、群组的媒体，直接以来源名作为目录
    ├── metadata.csv     # 该来源的元数据备份
    └── [媒体文件]
```

> 说明：全局统一的 SQLite 数据库位于 `data/telegrabber.db`（不在 downloads 下）；每个来源目录下另有 `metadata.csv` 作为物理备份。

这种组织方式的主要优势：

- 个人/私聊来源统一放在 `direct_messages` 目录下，避免散乱
- 频道、群组的媒体直接位于以来源命名的目录下，便于快速访问
- 每个来源单独的 `metadata.csv`，作为数据库之外的物理备份
- 根据媒体来源类型自动选择最优的保存位置

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
- 来源名称 (频道名、用户名等)
- 来源 ID (频道 ID、用户 ID 等)
- 来源链接 (t.me 格式的链接)
- 来源类型 (channel、group、bot、user、private_user 等)

同时每个来源目录下保留 `metadata.csv` 作为物理备份。

## 审计日志

所有机器人接收到的消息都会记录到 `data/audit.jsonl`，每条记录包含：

- 接收时间
- 消息类型（photo / video / animation / document / media_group / text / link）
- 完整的原始消息数据（`message.to_dict()`）
- 来源信息（chat_id、user_id、source 等）
- 备注信息

可通过 `.env` 中的 `AUDIT_LOG=false` 关闭审计日志。

## 许可证

本项目采用 MIT 许可证。详细信息请参阅 [LICENSE](LICENSE) 文件。
