# TeleGrabber Web

TeleGrabber 的 Web 管理界面，基于 **Vue 3 + Vite + Pinia + Element Plus**。

界面沿用 Telegram WebK 风格的深色布局，仅覆盖消息流、相册布局、来源筛选与媒体查看/删除；Element Plus 用于确认框、消息提示等交互组件。

样式按 DefaultFramework 的组织方式拆分：`assets/scss` 放 reset、主题变量、全局公共样式与媒体网格；组件和视图使用同目录同名 `.scss`，通过 `<style scoped lang="scss" src="./X.scss">` 引入。

## 开发

先启动后端，再启动前端：

```bash
npm install
npm run dev
```

前端配置在 `web/.env*`，与后端 `conf/config.toml` 解耦：

- `.env`：应用信息（`VITE_APP_TITLE`）
- `.env.development`：`VITE_PORT`、`VITE_OPEN`、`VITE_USE_HTTPS`、`VITE_API_PROXY_URL`、`VITE_DROP_CONSOLE`、`VITE_DROP_DEBUGGER`、SSL 证书路径
- `.env.production`：`VITE_API_URL=/`（同源）、`VITE_DROP_CONSOLE`、`VITE_DROP_DEBUGGER`
- `.env.local` / `.env.*.local`：本地覆盖，已忽略

Vite 只在该环境下设置了 `VITE_API_PROXY_URL` 时启用 `/api`、`/media`、`/thumb` 代理。后端端口以 `conf/config.toml` 的 `[web].port` 为准，修改后同步更新 `web/.env.development`。预压缩（`VITE_USE_COMPRESSION`）未启用，gzip 交给 Nginx 或 FastAPI `GZipMiddleware`。

## 构建

```bash
npm run build
```

产物输出到 `web/dist`，由 FastAPI 在 `/` 托管，`/assets` 提供带 hash 的静态资源。Docker 镜像构建阶段会自动执行这一步。

## 目录结构

```text
src/
├── api/            # 媒体 / 下载任务 / 存储管理接口（返回值已由 request.js 解包）
├── assets/scss/    # 全局 SCSS：reset / theme / global / media
├── components/     # 来源侧栏、顶栏、相册网格、气泡、媒体查看器等（样式与组件同名 .scss）
├── lib/            # 相册布局算法与媒体/日期工具函数
├── router/         # 单页路由（/ 欢迎页，/feed 消息流，/tasks 任务，/storage 存储，/status 状态）
├── store/          # Pinia 媒体列表状态与分页
├── utils/          # request.js 统一网络层（对齐 DefaultFramework）
├── views/welcome/  # 欢迎页（index.scss）
├── views/feed/     # 消息流主页面（index.scss）
├── views/tasks/    # 下载任务中心（index.scss）
├── views/storage/  # 存储统计与重复项（index.scss）
├── views/status/   # 系统状态与运行检查（index.scss）
├── App.vue
└── main.js
```

## 统一响应

后端所有 JSON 接口统一返回：

```json
{ "code": 10000, "msg": "成功", "data": {}, "requestId": "..." }
```

`code !== 10000` 为业务错误；本工具未启用登录，因此业务错误统一返回 HTTP 200，只有服务器/框架异常才使用非 200 状态码。`utils/request.js` 是唯一的错误弹窗出口，组件内不再重复 `ElMessage.error`。

## 认证说明

本工具为个人本地使用，不启用应用内登录鉴权。Web 后台默认只监听 `127.0.0.1`，请勿直接暴露到公网；如需远程访问，请在网络层使用 VPN、SSH 隧道或反向代理访问控制。
