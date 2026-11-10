# AGENTS.md - AI 智能体开发与协作规范

本文档为 AI Agent 在本工程内执行任何代码分析、文件编辑、重构与终端操作时必须严格遵循的全局准则。在执行任何任务前，优先以本文档规定的原则为准。

---

## 🚫 1. 杜绝旧逻辑兼容包袱（Zero-Legacy Policy）

- **坚决不保留向后兼容逻辑**：在重构、迭代或修改代码时，直接采用最新的标准设计与最优解，**严禁添加任何针对旧版本、旧数据结构、旧缓存字段或过时参数的兼容回退代码**（例如：旧字段回退判断、旧 `localStorage` key 兼容读取、过时的兼容别名等）。
- **彻底清理废弃代码**：一旦某个模块、字段、配置或 API 被新方案取代，必须将旧逻辑与旧实现彻底删除，保持代码库的绝对纯粹与精简，绝不遗留任何技术债务。

---

## 📦 2. 静态产物与 Git 提交边界

- **构建产物严禁进入 Git 仓库**：
  - 前端生产打包输出至 `web/dist/`，本地单体联调时可拷贝至后端 `public/` 目录。
  - `public/` 目录下由前端构建产生的所有文件（包括 `public/index.html`、`public/assets/` 等）已被 `.gitignore` 规则（`public/*`）全面忽略，**严禁以任何形式将构建产物添加到 Git 暂存区或提交到版本历史中**。
  - Git 中仅保留 `public/.gitkeep` 占位文件，以确保代码仓库克隆时静态目录结构完整。

---

## 🏗️ 3. 架构与工程规范

- **统一响应与错误处理**：后端对外接口统一使用 `internal/platform/gwe` 构建 JSON 响应与业务错误码，保持请求链路追踪（`requestId`）规范一致。
- **数据库基线与迁移同步**：新增或修改数据表时，全量初始化脚本（`deploy/init.sql`）与增量迁移脚本（`migrations/`）必须严格同步对齐。
- **角色与权限层级**：严格遵循 `sys_role` 的 0/1/2 阶梯层级鉴权模型（0: 超管, 1: 高管, 2: 普管），JWT Claims 中注入层级标识，前后端严密防范越权操作。
- **凭据与敏感信息安全**：前端敏感凭据（如记住账号密码）必须遵循 AES 密文存储，UI 保持企业级极简风格（对齐 `emw`）。

---

## 🛡️ 4. 真实数据与精准必要兜底规范（Truthful & Minimal Fallbacks Policy）

- **核心原则：非必要不兜底，真实反映数据现状**：
  - 只有在防范程序崩溃或明确需要空值占位等必要场景下才允许做防御兜底，严禁毫无节制地滥加默认值。
- **严禁捏造与臆测假数据（No Arbitrary / Hallucinated Fallbacks）**：
  - 严禁在视图层、状态管理或业务逻辑中硬编码捏造业务默认值（例如：`deployType || '本地开发环境'`、`roleName || '超级管理员'`）。
  - 如果数据尚未加载完成、未配置或字段为空，必须真实客观反映（如统一显示中立占位符 `'-'`、未配置或留空），绝不可捏造虚假信息欺骗用户或掩盖线上故障与配置失效。
- **严禁表单回填脑补污染真实数据（No Silent Mutation）**：
  - 在弹窗编辑表单初始化时，严禁给缺失数值赋值臆造的默认数据（例如：`editForm.age = row.age || 25`、`editForm.roleId = row.roleId || 3`）。
  - 数据回填必须原样保持真实状态（如 `row.age ?? null`、`row.roleId || row.role?.roleId`），严禁用户在不知情或仅修改其他字段时将臆测数据持久化写入数据库。
- **合法的必要兜底场景（Legitimate Fallback Scenarios）**：
  1. **容器防崩溃（Crash Prevention）**：在数据列表未返回时兜底为空数组（如 `const list = res.data?.list || []`），防止调用 `.map()` 或 `.forEach()` 发生空指针运行时崩溃。
  2. **中立客观占位符（Neutral Placeholders）**：表格或详情字段未填写时，统一采用 `'-'` 明确告知用户该项无数据（如 `row.phone || '-'`、`row.email || '-'`）。
  3. **标准路由跳转缺省（Route Defaults）**：在重定向参数不存在时提供基准路由（如 `const redirect = route.query.redirect || '/home'`）。
- **杜绝语法级滥用**：严禁在 `switch/case` 等逻辑判断中将 `||` 误用为分支条件（例如 `case "A" || "B"` 导致分支永远失效），多分支必须严格遵守语言规范的标准语法。

---

## 📢 5. 请求错误处理与单次弹窗规范（Single-Toast Error Policy）

- **单一真相源原则（Single Source of Truth）**：
  - 全局网络请求拦截器（[`request.js`](file:///home/syw/work/My/DefaultFramework/web/src/utils/request.js)）是系统所有网络异常与业务错误（`code !== 10000`）的**唯一法定弹窗出口**，统一调用 `ElMessage.error` 且启用 `grouping: true` 去重合并。
- **严禁业务组件二次弹窗（No Duplicate Error Toasts）**：
  - 视图组件中的 `try...catch` 仅用于业务流程控制与组件状态复位（例如 `loading.value = false`、`submitting.value = false`、开关状态回滚等）。
  - **严禁在组件的 `catch` 块中再次调用 `ElMessage.error`**，彻底杜绝一次接口失败触发两次重叠弹窗的劣质体验。
- **特殊自定义场景显式声明**：
  - 若特定业务调用确实需要静默处理或完全自定义错误 UI，必须在请求配置中显式传递 `{ skipErrorToast: true }` 或 `{ silent: true }`，方可由业务组件接管错误呈现。

---

## 🔒 6. Git 协作与用户独立暂存权边界（Git Operation Boundary）

- **AI 严禁操作暂存区与提交历史**：
  - AI 智能体在修复、重构或生成代码时，**严禁执行任何 `git add`（暂存）、`git commit`（提交）或 `git restore --staged`（撤销暂存）操作**。
  - 所有由 AI 修改或新增的代码必须完整保留在本地工作区（Unstaged），保留 Git 的最原始变更状态。
- **用户对代码具有绝对审核与暂存决定权**：
  - 用户在本地通过 `git diff` 逐行审查 AI 的改动，由用户决定哪些文件暂存、何时提交以及提交信息内容。
  - 即使任务完成或用户要求测试，AI 也仅可在本地执行验证指令（如 `go test`、`npm run build`），绝对不可擅自将文件添加到暂存区。

---

## 🔢 7. 表单数值与数据库零值契约规范（Form Zero-Value Contract）

- **前端表单回填保持客观真实（No False Zeroes）**：
  - 数字类型字段（如 `age`、`sort` 等）在无数据或未填写时，表单对象中统一显式初始化为 `null`（例如 `createForm.age = null`；编辑表单回填 `editForm.age = (row.age && row.age > 0) ? row.age : null`）。
  - 严禁在界面上默认将缺失值脑补展示为 `0` 或虚假数值（例如避免界面输入框显示荒谬的“0 岁”），确保输入框能正确显示占位提示文字（`placeholder`）。
- **提交后端时精准映射零值契约（Nullish Coalescing）**：
  - 表单向后端提交时，如该字段在数据库中属于非空整型（`int NOT NULL DEFAULT 0`），统一采用 ES2020 空值合并操作符将其安全归整为后端零值（例如 `age: form.age ?? 0`），杜绝因向后端传递 `null` 导致的解析异常或前后端契约断裂。

---

## 🔍 8. 端到端全链路全量审计规范（Exhaustive Cross-Layer Audit Policy）

- **杜绝局部修补思维（No Patch-Fixing Mindset）**：
  - 代码审查或缺陷修复时，严禁仅针对受影响的代码行做单点修补，必须以“端到端全链路”视角覆盖 **前端视图组件 -> API 请求层 -> 后端路由中间件 -> Service 业务逻辑 -> 数据库与模型契约** 五大层次。
- **全量闭环审计矩阵**：
  - 每次代码交付前，必须执行全维度编译与静态检查验证矩阵：
    1. **Go 静态分析**：`go vet ./...` 0 报错、0 警告；
    2. **Go 竞态检测**：`go test -race ./...` 保证无数据竞争（Data Race）；
    3. **Go 全包测试**：`go test -count=1 ./...` 全通过；
    4. **前端生产构建**：`npm run build` 0 报错、0 警告；
    5. **规范符合性**：0 违规 `ElMessage.error`、0 捏造默认值、0 破坏 Git 暂存边界。

