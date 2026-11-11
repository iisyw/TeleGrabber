# AGENTS.md - TeleGrabber 开发与协作规范

本文档是 AI Agent 在本工程内执行分析、修改、重构、评审和终端操作时必须遵循的准则。执行任务前，优先以本文档为准。

---

## 1. 项目定位与运行边界

- TeleGrabber 是**个人自用的 Telegram 媒体归档工具**，不是多租户 SaaS。
- 技术栈：
  - 后端：Python 3 + python-telegram-bot v21 + Pyrogram（User API）+ FastAPI + SQLite
  - 前端：Vue 3 + Vite + Pinia + Element Plus + SCSS
- 默认部署方式：
  - Web 后台只监听 `127.0.0.1`，不内置登录鉴权
  - 如需局域网/远程访问，由 VPN、SSH 隧道或反向代理负责访问控制
- 不实现浏览器下载功能：
  - 媒体由 Bot/User API 下载到项目机器的 `downloads/`
  - Web 只负责浏览、预览、检索、删除、标签/收藏/备注
  - 文件需要时直接从文件系统取用

---

## 2. 杜绝旧逻辑兼容包袱（Zero-Legacy Policy）

- 重构时直接采用当前最优设计，严禁保留旧字段、旧参数、旧配置、旧缓存、旧 API 的兼容分支。
- 已废弃的模块、字段、接口、配置和前端代码必须**彻底删除**，不保留别名、不保留“兼容读取”、不保留“旧数据回退”。
- 典型禁止项：
  - 旧 `.env` 配置读取、旧 Basic Auth/Session 登录回退
  - 旧 `static/` 页面路径、旧单一 `telegram.css`
  - 已删除的 `source_link2`、旧媒体组 `single` 标记
  - 旧 `public/` 构建产物、旧数据目录布局
- 数据库只保留当前 schema 基线。除用户明确要求外，不在 `init_db()` 中堆叠历史列迁移、旧任务清理或旧字段回填逻辑。
- 需要修复历史数据时，使用一次性维护脚本处理完后删除，不要把修复逻辑塞进正常启动流程，也不要长期保留维护脚本。

---

## 3. 代码结构与职责

```text
main.py              # 启动入口：配置、DB、Bot、Web、User API
core/                # 核心业务模块
core/config.py       # 读取 conf/config.toml 并导出配置常量
core/config_loader.py # TOML 解析、默认值、类型与范围校验
core/utils.py        # SQLite schema、媒体落库、删除、FTS
core/media_files.py  # 保存目录、文件名与扩展名
core/telegram_meta.py # 消息时间/ID、私有频道链接
core/thumbnails.py   # 缩略图生成、缓存与清理
core/audit.py        # 审计日志
core/task_manager.py # 下载任务持久化、进度、取消、批次
core/retry_service.py # 任务重试队列、优先级、Bot/User API 回退
core/runtime_state.py # Bot 运行状态与最近错误
core/user_api.py     # Pyrogram 同步封装、转发、链接解析、下载
bot/                 # 消息处理、媒体组、下载、按钮回调、按钮状态
webapp/app.py        # FastAPI 组装：中间件、异常、静态资源、SPA 回退
webapp/api_response.py # 统一响应/错误码/requestId
webapp/health.py     # 媒体文件健康检查与缓存
webapp/routers/      # media / sources / tasks / storage / status 路由
web/                 # Vue 3 前端；组件与视图同目录同名 .scss
downloads/           # 原始媒体（不入库）
data/                # SQLite、缩略图、审计日志、session
```

- 不要新增职责不清的“万能模块”；公共逻辑放入已有模块或独立单一职责模块。
- 前端组件样式使用同目录同名 `.scss`，通过 `<style scoped lang="scss" src="./X.scss">` 引入。
- 全局样式只放 reset、主题变量、通用按钮/徽标/管理页骨架；不要再恢复单一全局 CSS。

---

## 4. 数据库与数据契约

- SQLite 是唯一数据库，数据库文件为 `data/telegrabber.db`，开启 WAL。
- `utils.init_db()` 是**唯一 schema 基线来源**：
  - 修改表结构时，直接更新 `CREATE TABLE` 与 `utils._schema_docs`
  - 不添加旧列迁移、旧值回填、旧表删除逻辑，除非用户明确要求升级旧库
  - 新装用户从空库启动即可
- 所有数据库写入必须通过 `utils._db_lock` 或 `task_manager._lock` 串行化，避免 `database is locked`。
- `media_metadata` 是媒体唯一索引：
  - `file_unique_id` 唯一，用于去重
  - 原始媒体只存一份；缩略图是派生文件，不写入媒体记录
  - 来源链接只保留 `source_link1`；公开频道用用户名链接，私有频道用 `t.me/c` 链接
- `download_tasks`：
  - 每次媒体组下载/重下生成独立 `batch_id`
  - 任务中心按 `batch_id` 分组，不能只按 `media_group_id` 合并
  - 成功任务必须补齐 `downloaded_bytes`，不能长期显示 `0B / 总大小`
- 旧字段、旧状态值、旧兼容标记不得重新引入。

---

## 5. 配置边界

- 后端配置：`conf/config.toml`
  - `conf/config.example.toml` 必须与代码字段完全同步
  - `conf/config.toml` 含敏感信息，已被 `.gitignore` 忽略
  - 不再使用 `.env`、`python-dotenv`
- 前端配置：`web/.env*`（Vite 专用）
  - Vite 只读取 `VITE_*`
  - 后端端口由 `[web].port` 决定，需同步更新 `web/.env.development` 的代理目标
  - 前端不得读取后端 `config.toml`
- `save_dir` 推荐使用绝对路径；相对路径依赖进程工作目录，容易造成媒体 404。

---

## 6. API 与错误处理

- 所有 `/api/*` 响应统一使用 `webapp/api_response.py`：
  - 成功：`{ code: 10000, msg, data, requestId }`
  - 业务错误：HTTP 200 + `code != 10000`
  - 资源不存在：`40004`
  - 参数错误：`40006`
  - 禁止访问：`40008`
  - 系统错误：`50000`
- 前端网络层唯一入口：`web/src/utils/request.js`
  - 自动解包 envelope
  - 统一 `ElMessage.error({ grouping: true })`
  - 业务组件 `catch` 只做流程复位，禁止再次弹错误
  - 需要静默处理时显式传 `{ silent: true }` 或 `{ skipErrorToast: true }`
- 媒体 URL 规则必须前后端一致：
  - `unsorted/<filename>`
  - `direct_messages/<source_name>/<filename>`
  - `<source_name>/<filename>`
- 不要把下载、重试、删除等写操作做成 GET。

---

## 7. 前端规范

- Vue 3 `<script setup>`，组合式 API；不要引入 Vuex 或旧版写法。
- 路由：欢迎页 `/`、消息流 `/feed`、下载任务 `/tasks`、存储管理 `/storage`、系统状态 `/status`。
- 媒体列表：
  - 分页使用 keyset（`cursor_time` + `cursor_id`），不要恢复 offset 分页
  - 消息流使用虚拟滚动，不要一次渲染全部记录
- 媒体预览：
  - 图片/视频通过 `/media/...` 访问
  - 视频封面优先 Telegram 缩略图，缺失时用 ffmpeg 抽帧
  - 不提供浏览器下载按钮
- Element Plus 按需引入，不恢复全局全量 CSS/插件。
- 复制/参考 DefaultFramework 时，只借鉴结构（request.js、scss 组织、响应规范），不要把 Go/GWE/JWT/角色体系带进来。

---

## 8. 真实数据与必要兜底

- 不允许捏造业务数据：
  - 缺失字段显示 `'-'`
  - 未配置显示“未配置”，不要编造默认环境名、默认角色、默认密码等
- 允许的兜底仅限：
  - 数据未加载时列表为空数组，防止 `.map()` 崩溃
  - 中立占位符 `'-'`
  - 路由缺省跳转
- 表单回填必须保持真实值，不得把缺失数字脑补成 0；提交时按后端非空字段契约用 `?? 0` 归整。

---

## 9. 安全、凭据与部署

- 当前没有内置登录鉴权，这是明确的产品选择：
  - 不要重新添加 Basic Auth、Session Cookie、CSRF、登录页
  - 默认 `[web].host = "127.0.0.1"`
  - 修改为 `0.0.0.0` 前必须提醒用户网络暴露风险
- Bot Token、User API API_ID/API_HASH、代理凭据只放 `conf/config.toml`，不得写入代码或日志。
- Docker：
  - 镜像内构建前端，安装 ffmpeg
  - 只挂载 `conf/config.toml`、`downloads/`、`data/`
  - 不再挂载旧 `static/`
- 反向代理必须同时转发 `/api/`、`/media/`、`/thumb/`。

---

## 10. 静态产物与 Git 边界

- 构建产物严禁进入 Git：
  - `web/dist/`
  - `web/node_modules/`
  - `conf/config.toml`
  - `downloads/`
  - `data/`（含 SQLite、session、审计日志、缩略图）
- AI 严禁执行 `git add`、`git commit`、`git restore --staged`。
- 所有修改保留在工作区，由用户自行审查、暂存、提交。
- 验证只允许本地执行编译、测试、构建，不得擅自提交。

---

## 11. 并发与线程模型

- Bot 主事件循环与 Web/uvicorn 线程是分离的：
  - 不要在 Web 线程直接调用 asyncio 对象
  - User API 的同步封装通过 `run_coroutine_threadsafe` 调度
  - Bot API 下载在需要时通过独立 Bot 实例或主事件循环执行
- 下载重试队列：
  - `retry_service` 使用独立 worker 线程与优先级队列
  - 暂停只对重试队列中尚未开始的任务生效
  - 下载中取消只能在当前下载步骤结束后生效
- 缩略图生成使用独立线程池与信号量，避免阻塞下载主流程。

---

## 12. 端到端验证矩阵

每次代码交付前至少执行：

1. Python 编译：
   ```bash
   python3 -m py_compile main.py core/*.py webapp/app.py webapp/api_response.py webapp/health.py webapp/routers/*.py bot/*.py
   ```
2. 后端测试：
   ```bash
   venv/bin/python -m unittest discover -s tests -q
   ```
3. 前端构建：
   ```bash
   cd web && npm run build
   ```
4. 接口烟雾测试：
   - `/healthz`
   - `/api/media`
   - `/api/sources`
   - `/api/tasks`
   - `/api/status`
5. 规范符合性：
   - 0 处业务组件重复错误弹窗
   - 0 处捏造默认值
   - 0 处旧字段/旧配置兼容分支
   - 0 破坏 Git 暂存边界

---

## 13. 审查原则

- 修复缺陷必须覆盖：前端 → API 请求层 → 后端路由 → Service/下载逻辑 → SQLite/文件系统。
- 不要只改一行让现象消失；要确认真实数据、路径、线程和状态转换都正确。
- 不为了“以后可能用”增加抽象、配置项或回退分支。
- 发现旧逻辑时优先删除，而不是再加一层兼容包装。
