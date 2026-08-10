# 多客户工作区实施方案

> 状态：Phase 7 PF Customer Profile 已完成代码与真实文件验收
> 对应设计：[多客户工作区设计](../product/multi-customer-workspace-design.md)
> 当前实施阶段：Phase 7 出口验收完成；下一阶段为 Phase 8 多客户加固
> 上一阶段：Phase 5（Task 5.0–5.8 与出口验收已完成）

## 1. 目的

本方案用于把现有仅面向 RO 的本地单用户工作台，演进为可配置、可切换客户的多工作区应用。

实施完成后：

- 用户不需要登录；
- 一个客户可以配置一个或多个工作区；
- 每个工作区绑定一个 Customer Profile 和一个 base 文件；
- 顶部栏始终显示当前工作区，并可快速切换；
- 同一时刻只有一个当前工作区参与浏览、编辑、预览和导出；
- 原 RO CLI、API 和工作台流程保持兼容；
- 新客户只能通过独立 Profile 接入，不能把客户判断散落到路由或前端。

本文是实施顺序和验收门槛的依据。产品、数据模型、API 和交互决策以对应的设计文档为准。

## 2. 为什么不能只增加一个“当前客户”字段

当前实现有三个互相关联的单客户假设：

1. 核心包在模块加载时取得固定的 RO schema 和规则对象；
2. API session 只记录 base 文件，缓存也只以 base 文件路径为主要身份；
3. 前端只在 `localStorage` 中记录一个 base 路径，并在打开文件时直接重置当前状态。

如果只在设置中新增 `customer` 并继续复用这些对象，切换后可能出现旧 schema、旧缓存或旧下载被新客户流程复用的问题。根因不是设置页面缺一个字段，而是“客户身份”尚未进入核心执行上下文、session 和缓存边界。

因此实施顺序必须是：

```mermaid
flowchart LR
    A["可复用前端交互骨架"] --> B["冻结 RO 行为基线"]
    B --> C["RO Profile 化"]
    C --> D["核心执行上下文隔离"]
    D --> E["Workspace 与 Session 后端"]
    E --> F["真实 API 接入与发行"]
    F --> G["第二客户接入"]
```

## 3. 实施纪律

### 3.1 一次只改变一个维度

- Profile 基础阶段只封装现有 RO 行为，不改变字段规则、模板布局和文件名；
- 前端骨架直接使用正式组件、类型和状态模型，临时内容只限于 mock service；
- 工作区阶段只改变配置、session 和切换机制，不同时接入第二客户；
- 第二客户在工作区机制稳定后独立接入；
- 任何阶段均不得把业务判断放入 FastAPI 路由或 Vue 组件。

### 3.2 兼容优先

- `ro-generate` 不传 `--profile` 时仍使用 RO；
- 旧 `/api/session/open` 在过渡期保留，并默认使用 RO；
- 现有 RO mapping 的渲染结果必须保持一致；
- 现有错误码、CLI 退出码和文件命名不改变；
- 工作区配置损坏或切换失败时，不得破坏最后一个可用工作区。

### 3.3 Profile 身份必须贯穿全链路

以下对象不得只依赖 base 路径推断客户：

- schema 和业务规则；
- 模板与 mapping 路径；
- workbook snapshot/cache；
- API session；
- 预览、编辑和导出请求；
- 前端当前工作台状态。

### 3.4 按 Phase 增量细化

遵循仓库文档增量规则，本文保留已完成阶段的实施记录，并只把当前阶段细化到任务级。Phase 7 已根据 PF 实际资料补充并完成；Phase 8 仍只保留目标级描述，待进入后再细化。

## 4. 路线图

| Phase | 内容 | 交付状态 |
| --- | --- | --- |
| 4.5 | 正式前端组件、状态模型、service 契约和 mock 交互确认 | 已完成 |
| 5 | Profile、核心执行上下文、WorkspaceStore、SessionManager、后端 API、CLI Profile | 已完成（含出口验收） |
| 6 | 真实 API 接入、旧配置迁移、端到端验收和发行 | 已完成代码验收（Task 6.0–6.3；Windows CI/最终签字待运行） |
| 7 | PF Profile、模板和差异规则接入 | 已完成代码与真实文件验收 |
| 8 | 多客户回归加固、配置升级和运维工具 | 后续，目标级 |

## 5. Phase 4.5：可复用前端交互骨架

Phase 4.5 不是独立静态原型，而是把 Phase 6 的正式 UI 组件提前实现。后续只替换数据适配层，不重新制作页面。

### 5.1 Task 4.5.0：建立前端领域类型和 service 契约

目标：先固定前端理解的工作区对象和操作语义，使 mock 与真实 API 使用同一个接口。

建议新增：

```text
frontend/src/services/
  workspace.ts
  workspace.mock.ts

frontend/src/stores/
  workspace.ts
```

任务：

1. 在 `workspace.ts` 定义正式类型：
   - `ProfileSummary`；
   - `CustomerWorkspace`；
   - `WorkspaceStatus`；
   - `WorkspaceValidationResult`；
   - `WorkspaceBootstrap`；
   - `WorkspaceActivationResult`；
   - 稳定错误 code。
2. 定义 `WorkspaceService` 接口，覆盖：
   - profiles/workspaces 列表；
   - create/update/delete；
   - validate draft input（不落盘）、validate workspace 和 activate；
   - bootstrap。
3. Pinia store 只依赖 `WorkspaceService`，不直接导入 mock 数据；
4. 状态中只保留一个 `currentWorkspaceId`，不为每个工作区保存可冲突的 `active` 布尔值；
5. service 返回结构与设计文档 §13 对齐，Phase 5 后端若需调整必须回写设计和前端契约。

完成条件：

- 组件不知道当前使用 mock 还是真实 HTTP；
- `profile_id`、`workspace_id` 和 `session_id` 含义没有混用；
- TypeScript type-check 通过。

### 5.2 Task 4.5.1：实现可替换的 MockWorkspaceService

目标：在没有 Phase 5 后端的情况下，完整演示交互状态。

任务：

1. 提供至少两个工作区和两个 Profile 展示项；第二个 Profile 只用于 UI 演示，不代表业务已支持；
2. 在内存中模拟 CRUD、validate、activate 和 bootstrap；
3. 可确定性模拟：
   - 激活成功；
   - 文件缺失；
   - schema 不匹配；
   - 激活失败并保留原工作区；
   - 网络/服务延迟；
   - active 操作期间禁止重复切换。
4. mock 不读取真实 Excel、不调用现有 `/api/session/open`、不写用户 `localStorage` 或工作区配置；
5. mock 数据、延迟和故障开关集中在一个适配器中，组件内不得出现 `if mock`。

完成条件：

- 删除 `workspace.mock.ts` 不会删除任何组件、类型或表单逻辑；
- 所有失败场景可重复触发，便于交互评审；
- mock 客户名称明确标注“演示”，不被误认为已接入客户。

### 5.3 Task 4.5.2：实现正式工作区组件

建议新增：

```text
frontend/src/components/workspace/
  WorkspaceSwitcher.vue
  WorkspaceSettings.vue
  WorkspaceForm.vue
  WorkspaceStatusBadge.vue
```

任务：

1. `WorkspaceSwitcher`：
   - 顶部显示当前工作区、Profile 和 base 文件名；
   - 下拉切换和“管理工作区”入口；
   - 切换时保留旧页面内容并显示 loading；
   - 失败时仍显示旧工作区。
2. `WorkspaceSettings`：
   - 列表、新建、编辑、删除、验证和设为当前；
   - 保存配置与激活分开；
   - 禁止直接删除当前工作区。
3. `WorkspaceForm`：
   - 显示名称、Profile、base 文件路径；
   - Profile 选项来自 service，不硬编码客户业务；
   - 在路径字段旁提供“检测路径”，显示 checking/ready/file_missing/permission_denied/profile_not_found/schema_mismatch 状态；
   - 检测只针对当前草稿，不自动保存，修改 Profile 或路径后清除旧结果。
4. `WorkspaceStatusBadge` 统一显示：
   - `unchecked`；
   - `ready`；
   - `file_missing`；
   - `permission_denied`；
   - `profile_not_found`；
   - `schema_mismatch`。
5. 组件沿用现有 CSS token，不引入设计系统依赖。

主要影响文件：

- `frontend/src/components/layout/TopBar.vue`
- `frontend/src/components/workspace/`
- `frontend/src/stores/workspace.ts`
- `frontend/src/styles/tokens.css`

完成条件：

- 1366 × 768 下顶部栏和主操作不互相挤压；
- 长名称有截断和完整提示；
- 键盘焦点、关闭、确认和错误反馈路径完整；
- UI 组件可原样用于 Phase 6。

### 5.4 Task 4.5.3：以开发模式接入当前页面

目标：在真实工作台布局中评审交互，同时不改变正式 RO 流程。

任务：

1. 只在 `import.meta.env.DEV` 且显式启用原型参数/环境开关时装配 `MockWorkspaceService`；
2. 默认 `pnpm run dev` 和生产 build 继续使用当前 RO 页面；
3. 原型模式可覆盖以下完整流程：
   - 无配置首次启动；
   - 新建、验证并激活第一个工作区；
   - A → B → A；
   - 目标无效时保留 A；
   - 编辑当前工作区后要求重新激活；
   - 删除非当前工作区并拒绝删除当前工作区；
   - 编辑/预览/导出繁忙状态下禁用切换。
4. 不提前修改现有 `ro-workbench-base-path` 的读取和迁移逻辑；该逻辑留到真实后端接入阶段。

完成条件：

- 不启用开发开关时，现有 RO 页面和 API 调用不变；
- 生产构建不会默认进入 mock 模式；
- 用户可在当前工作台布局中确认完整交互流程。

### 5.5 Task 4.5.4：交互测试和确认

任务：

1. 让 `MockWorkspaceService` 显式实现正式接口，通过 TypeScript type-check 验证 service contract；
2. 为原型增加 Playwright 场景，覆盖成功切换、失败回滚、CRUD、新增/编辑表单的路径检测和繁忙禁用；当前不为此阶段单独引入前端单元测试框架；
3. 运行：

   ```bash
   cd frontend
   pnpm run type-check
   pnpm run build
   pnpm run test:e2e
   ```

4. 记录交互评审结论；任何字段、状态或流程调整同步回设计文档和 service contract。

### 5.6 Phase 4.5 出口门槛

进入 Phase 5 前必须同时满足：

- 工作区切换器和设置使用正式组件，不存在另一套临时页面；
- mock 只存在于可替换 service adapter；
- 当前 RO 正式入口不受影响；
- 用户已确认首次配置、切换、失败恢复和工作区管理流程；
- TypeScript type-check、build 和相关 Playwright 场景通过；
- 前端 service contract 与设计文档一致，可作为 Phase 5 API 验收输入。

## 6. Phase 5：Profile 与工作区后端基础

### 6.1 Task 5.0：冻结 RO 行为基线 ✅

目标：在结构重构前留下足以判断“行为是否改变”的自动化证据。

任务：

1. 记录当前测试总数和以下命令的结果：

   ```bash
   uv run pytest packages/ro_generator packages/ro_workbench_api -q
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy packages
   cd frontend && pnpm run build
   ```

2. 为黄金回归 PO `4500030844` 固化以下 RO 契约：
   - 四类文档中已支持的主体组合；
   - 文档字段值、blocking error 和 warning；
   - 输出文件名、sheet 名和 zip 名；
   - CLI JSON 状态和退出码。
3. 为合成 fixture 固化以下边界：
   - 缺失 SAP、INV#、FACTORY DOC NO. 和价格时的阻断结果；
   - SK/YM 请求 PO 时的阻断结果；
   - Invoice/PL 使用 `SHIP QTY`；
   - PI/PO 使用客户 PO 数量。
4. 对现有 API session、预览、编辑、导出和下载行为增加必要的契约测试。

主要文件：

- `packages/ro_generator/tests/`
- `packages/ro_workbench_api/tests/test_app.py`
- `tests/fixtures/`

执行记录（2026-08-07）：

- Task 5.0 冻结时 `uv run pytest packages/ro_generator packages/ro_workbench_api -q`：469 个用例通过；加入 Task 5.1 契约测试后为 477 个，当前已增加到 498 个；
- `uv run ruff check .`：通过；
- `uv run ruff format --check .`：59 个文件已格式化；
- `uv run mypy packages`：57 个源文件无类型错误；
- `cd frontend && pnpm run build`：通过；
- 前端最终回归：type-check、完整 Playwright 25 个场景均通过。

新增 `packages/ro_generator/tests/test_ro_baseline.py`，锁定合成 fixture 的黄金 PO、数量来源、可用 PO 和缺 SAP 阻断结果。真实 `RO DATA BASE.xlsx` 未入库；当前合成黄金 PO `4500030844` 仍因缺少 reel 对应客户 PO 行而保持 `QTY_MISSING` 阻断，这个状态是已知基线，不等同于真实业务成功快照。

完成条件：

- Task 5.0 的历史基线为 477 个用例；当前全量后端测试基线为 506 个用例；
- 前端 build 通过；
- 已有 RO 行为可由测试判断，而不是依靠人工打开 Excel 猜测。

### 6.2 Task 5.1：建立 Profile 模型和注册表 ✅

目标：把“RO 是当前唯一客户”改造成“RO 是默认 Profile”，但业务行为不变。

新增建议：

```text
packages/ro_generator/src/ro_generator/profiles/
  __init__.py
  base.py
  registry.py
  ro.py
```

任务：

1. 在 `profiles/base.py` 定义：
   - `CustomerProfile`；
   - `GenerationContext`；
   - `CustomerRules` 协议；
   - profile 资产位置和能力声明。
2. 在 `profiles/registry.py` 提供：
   - 按 `profile_id` 查询；
   - 列出可用 Profile；
   - 重复 ID、未知 ID、非法配置的稳定错误。
3. 在 `profiles/ro.py` 封装现有 RO：
   - schema；
   - seller/buyer 链段；
   - 数量、价格、字段和校验规则；
   - 支持的单据矩阵；
   - 文件命名和发票分组行为。
4. 注册 `ro` 为默认 Profile。
5. 增加 Profile 加载、重复 ID、未知 ID 和 RO 默认值测试。

主要影响文件：

- `packages/ro_generator/src/ro_generator/models.py`
- `packages/ro_generator/src/ro_generator/errors.py`
- `packages/ro_generator/src/ro_generator/profiles/`
- `packages/ro_generator/tests/`

执行记录（2026-08-07）：

- 新增 `ro_generator.profiles.base`：`CustomerProfile`、`GenerationContext`、`CustomerRules`、`ProfileAssets` 和 `ProfileCapabilities`；
- 新增 `ro_generator.profiles.registry`：默认 Profile、列表、按 ID 查询以及重复/未知/非法配置错误码；
- 新增 `ro_generator.profiles.ro`：以现有 `base_schema`、主体链段、数量来源、价格列、单据能力矩阵、文件命名和发票分组策略声明 RO；
- 注册表默认只提供 `ro`，没有改变现有 CLI/API 的调用入口；
- 新增 `packages/ro_generator/tests/test_profiles.py`，Profile 相关测试通过。

完成条件：

- 可以通过 registry 显式取得 `ro`；
- 核心现有入口尚未改变行为；
- 不存在以 `if customer == ...` 代替规则对象的实现。

### 6.3 Task 5.2：把 RO 资产迁入 Profile 命名空间 ✅

目标：模板、mapping 和 base schema 都由 Profile 自己定位，避免第二客户复用 RO 目录。

目标目录：

```text
customer_profiles/
  ro/
    profile.yaml
    base_schema.yaml
    templates/
      gs/
      emax/
      sk/
      ym/
```

任务：

1. 将原 `templates/base_schema.yaml` 和 RO 模板/mapping 迁移到 `customer_profiles/ro/`；
2. `profile.yaml` 只保存声明式元数据和资产引用，不承载复杂业务表达式；
3. 修改 `resources.py`，统一处理源码运行和 PyInstaller bundle 中的 Profile 资源；
4. 修改 `template_mapping.py`，让模板路径相对当前 Profile 根目录解析，移除依赖固定目录层数的 `parent.parent...`；
5. 修改 `generator.builtin_mapping_path()`，通过 Profile 查找 mapping；
6. 修改 `ro-workbench.spec`，打包整个 `customer_profiles` 目录；
7. 校验所有 mapping 的模板引用、版本和单元格仍有效。

主要影响文件：

- `customer_profiles/ro/`
- `packages/ro_generator/src/ro_generator/resources.py`
- `packages/ro_generator/src/ro_generator/template_mapping.py`
- `packages/ro_generator/src/ro_generator/generator.py`
- `packages/ro_workbench_launcher/ro-workbench.spec`
- 与旧 `templates/` 路径相关的测试和文档

迁移约束：

- 文件移动和路径解析修改应在同一提交范围内完成，避免仓库处于无模板状态；
- mapping 内容不做业务修改；
- 对外不暴露安装目录绝对路径。

执行记录（2026-08-07）：

- 新增 `customer_profiles/ro/profile.yaml`，只声明 RO Profile 元数据和资产引用；
- 将 1 份 base schema、12 个 workbook 和 18 份 mapping 迁入 `customer_profiles/ro/`；
- `resources.py` 新增 Profile 根目录和 manifest 标记查找，源码与 PyInstaller 资源使用同一套路径规则；
- `template_mapping.py` 按当前 Profile 根目录解析相对模板路径，保留绝对路径用于临时 mapping/测试 fixture；
- `generator.builtin_mapping_path()` 改为通过默认 Profile 的资产声明查找 mapping；
- `ro-workbench.spec` 改为整体打包 `customer_profiles/`，并补充 Profile 模块 hidden imports；
- 新增全量 mapping 加载校验，18/18 份 mapping 的模板引用、版本和单元格校验通过；
- 核心包与工作台后端全量回归、ruff 和 mypy 均通过。

完成条件：

- 18 份 RO mapping 全部通过加载校验；
- 源码模式、CLI 模式和打包资源定位使用同一套 Profile 路径规则；
- 仓库中不再有核心代码硬编码 `templates/<seller>`。

### 6.4 Task 5.3：消除 RO 进程级隐式单例 ✅

目标：一次业务执行显式绑定一个不可变 `GenerationContext`。

任务：

1. 将 `base_schema.py` 中无参进程单例改为按 Profile 加载和缓存；
2. 移除模块加载时捕获 schema 的全局变量；
3. 让以下模块从 context/profile 获取规则和 schema：
   - `schema.py`；
   - `workbook_reader.py`；
   - `validator.py`；
   - `resolver.py`；
   - `seller_filter.py`；
   - `line_rules.py`；
   - `header_rules.py`；
   - `totals_rules.py`；
   - `invoice_groups.py`；
   - `invoice_inspection.py`；
   - `document_model.py`；
   - `workbook_snapshot.py`；
   - `workbench_service.py`；
   - `generator.py` 和 `packager.py`。
4. 为减少一次性破坏，可以保留短期兼容入口，但兼容入口必须显式取得默认 `ro` context 后再调用新实现；
5. 保证同一进程可先后创建两个不同 Profile context，且 schema/rules 不串用。

执行记录（2026-08-07）：

- `GenerationContext` 规范化 base 文件身份，并暴露绑定的 schema/rules；新增请求级 `profile_scope`，作用域退出后自动恢复；
- `base_schema()` 改为按 Profile schema 路径缓存的兼容入口，不再由核心模块保存 `_bs`/`_BASE_SCHEMA` 等 RO schema 全局对象；
- `WorkbookReader`、结构校验、resolver、snapshot、invoice inspection、document model 和 generator 均支持从 Profile schema/rules 读取；
- `generate`、`preview`、invoice group 预览/导出和工作台服务新增可选 `GenerationContext`，旧入口继续默认 RO；
- workbook cache 逻辑键纳入 `(profile_id, resolved_base_path)`，同一 base 文件在不同 Profile 下不会复用快照；
- 新增 Profile 作用域隔离和同一路径跨 Profile cache 隔离测试。

完成条件：

- 核心执行路径中没有“导入模块时固定为 RO”的 schema/rules；
- 同一函数调用所需 Profile 身份可从参数或 context 追溯；
- Task 5.3 完成时全量 RO 回归测试通过（480 个 Python 用例）；后续 WorkspaceStore、SessionManager 和工作区 API 测试加入后为 503 个，Task 5.8 CLI 测试加入后当前为 506 个。

### 6.5 Task 5.4：隔离 workbook 缓存 ✅

目标：相同 base 路径在不同 Profile 下也不能命中同一个逻辑缓存。

任务：

1. 将缓存的逻辑键改为：

   ```text
   (profile_id, resolved_base_path)
   ```

2. cache entry 继续保存 size + mtime_ns 文件签名，命中时复核，变化后替换同一逻辑 key 的 snapshot；
3. 保持当前 workbook cache 默认 TTL 为 30 分钟；
4. 工作区更新 base 路径或 Profile 后，使旧缓存自然失效或精确失效；
5. 增加相同文件路径、不同 Profile 的隔离测试，以及文件变化后的重建测试。

主要影响文件：

- `packages/ro_generator/src/ro_generator/workbook_cache.py`
- `packages/ro_generator/src/ro_generator/workbook_snapshot.py`
- `packages/ro_generator/src/ro_generator/workbook_editor.py`

执行记录（2026-08-07）：

- cache key 已改为 `(profile_id, resolved_base_path)`，文件签名仍按 `mtime_ns + size` 复核；
- `get_snapshot`、精确失效和工作台服务均支持显式 `GenerationContext`；兼容无 context 入口默认使用 RO；
- 保留 30 分钟 TTL，并增加同一 base 路径跨 Profile 的独立快照测试。

完成条件：

- cache lookup 不能缺少 `profile_id`；
- 现有 30 分钟 TTL 和文件签名行为不退化。

### 6.6 Task 5.5：实现 WorkspaceStore ✅

目标：在本机可靠保存工作区和当前工作区 ID。

建议新增：

```text
packages/ro_workbench_api/src/ro_workbench_api/
  workspace_store.py
```

任务：

1. 按设计文档实现 `CustomerWorkspace` 和版本化 JSON；
2. 用 `platformdirs` 选择用户配置目录，并增加相应依赖；
3. 测试允许通过 `RO_WORKBENCH_CONFIG_DIR` 指向隔离目录；
4. 使用临时文件、flush/fsync、原子替换写入；
5. 支持：
   - list/get/create/update/delete；
   - 读取和更新 `current_workspace_id`；
   - 名称非空、Profile 存在、ID 唯一；
   - 当前工作区不可直接删除；
   - 损坏 JSON 不覆盖原文件，并返回稳定错误；
   - 配置版本迁移入口。
6. store 只管理配置，不直接加载 workbook。

测试场景：

- 首次启动无配置；
- 创建第一个工作区；
- 重启后恢复；
- 原子写失败；
- 损坏 JSON；
- 删除普通工作区和拒绝删除当前工作区；
- 未知 Profile；
- 更新 base 路径后保留稳定 workspace ID。

完成条件：

- 配置写入失败不会丢失最后一次有效配置；
- store 测试不读写真实用户配置目录；
- 配置模型不依赖 FastAPI request 对象。

执行记录（2026-08-07）：

- 新增 `ro_workbench_api.workspace_store.WorkspaceStore`、`CustomerWorkspace` 和版本化 `WorkspaceSettings`；
- 默认配置目录使用 `platformdirs.user_config_dir("RO Workbench")`，测试和便携模式可通过 `RO_WORKBENCH_CONFIG_DIR` 或构造参数隔离；
- create/update/delete/list/get、当前工作区指针和 `last_opened_at` 均通过进程内 `RLock` 保护；Profile ID 在写入前由注册表校验，store 不读取 base 文件；
- 写入使用临时文件、`flush`、`fsync` 和 `os.replace`，原子替换失败时保留原配置；损坏 JSON 返回 `WORKSPACE_CONFIG_INVALID`，并提供 v0 → v1 迁移入口；
- 新增 9 个 WorkspaceStore 测试，覆盖首次启动、重启恢复、CRUD、当前工作区删除保护、未知 Profile、损坏配置、原子写失败、版本迁移和环境变量目录；
- Task 5.5 完成时全量后端测试为 489 个；加入 SessionManager 测试后为 498 个，工作区 API 测试加入后为 503 个，Task 5.8 完成后当前为 506 个；ruff、format 和 mypy 均通过。

### 6.7 Task 5.6：实现 SessionManager 和激活事务 ✅

目标：把工作区验证、session 创建和当前工作区提交组成两阶段激活流程。

建议新增：

```text
packages/ro_workbench_api/src/ro_workbench_api/
  session_manager.py
```

任务：

1. 扩展 `SessionInfo`：
   - `workspace_id`；
   - `profile_id`；
   - `base_file`；
   - `state: active | draining`；
   - `drain_until`；
   - 原有临时目录和时间字段。
2. `SessionManager` 负责创建、查询、过期、切换和清理 session；
3. 激活流程严格按以下顺序：
   - 读取工作区；
   - 验证 Profile 和 base 文件；
   - 构建 workbook snapshot；
   - 准备一个尚不可路由的候选 session；
   - 原子提交 `current_workspace_id`；
   - 在同一临界区将候选发布为 active，并把旧 session 标记为 draining；
4. 任一步失败均保留旧工作区和旧 active session；
5. 提交后的内存发布若异常，恢复旧 `current_workspace_id` 并丢弃候选；进程崩溃后由 bootstrap 按持久化配置重建；
6. draining session 只允许下载已生成文件，宽限期默认 5 分钟；
7. session TTL 保持当前 1 小时；
8. 并发激活使用进程内锁串行提交，后一次请求不得覆盖一个尚未完成的未知中间态。

测试场景：

- 激活成功；
- 未知 workspace/profile；
- base 不存在、不可读、schema 不匹配；
- snapshot 创建失败后回滚；
- 连续切换 A → B → A；
- 并发激活；
- draining 只能下载；
- 5 分钟后清理；
- 1 小时 session TTL；
- 重启后根据 store 重新建立 session，而不是复用旧 temp 目录。

完成条件：

- `current_workspace_id` 只在新 session 完整可用后更新；
- 任一业务 API 都能从 session 取得 workspace/profile/base 三元组；
- 切换失败不影响旧工作台继续使用。

执行记录（2026-08-07）：

- 新增 `ro_workbench_api.session_manager.SessionManager`、`SessionInfo` 和 `SessionActivation`；
- 激活先读取工作区、校验 Profile/base 文件并构建 `GenerationContext` + snapshot，再提交 current 指针和 active session；候选 session 在发布前不可路由；
- 切换时旧 session 进入 `draining`，默认 5 分钟内仅允许下载侧读取；active session TTL 保持 1 小时；
- 持久化提交或内存发布失败均恢复旧 workspace/session，并清理候选临时目录；进程重启通过 `restore_current()` 创建全新的临时 session；
- 提供进程内串行 `activate()` 与非阻塞 `try_activate()`，覆盖 A→B、失败回滚、未知 Profile、缺失文件、schema 失败、并发、draining 和 TTL 清理；
- 新增 9 个 SessionManager 测试；全量后端测试当前为 498 个，ruff、format 和 mypy 均通过。

### 6.8 Task 5.7：提供工作区 API 并兼容旧入口 ✅

目标：实现设计文档 §13 的端点，同时让现有前端在 Phase 6 前仍可运行。

任务：

1. 在 `app.py` 中接入但不内嵌 store/session 业务逻辑；
2. 实现：
   - `GET /api/profiles`；
   - `GET /api/workspaces`；
   - `POST /api/workspaces`；
   - `PATCH /api/workspaces/{workspace_id}`；
   - `DELETE /api/workspaces/{workspace_id}`；
   - `POST /api/workspaces/{workspace_id}/validate`；
   - `POST /api/workspaces/validate`（不落盘的 Profile/base 路径检测）；
   - `POST /api/workspaces/{workspace_id}/activate`；
   - `GET /api/bootstrap`。
3. 统一映射设计文档中的稳定错误码；
4. 新 API 的数据、问题、编辑、预览和导出只依赖 session 身份，不信任客户端重复提交的 `base_file`；
5. 旧 `/api/session/open` 暂时保留：
   - 默认 Profile 为 `ro`；
   - 不修改持久化的 `current_workspace_id`；
   - 没有持久化当前工作区时，可以替换另一个临时 legacy session；
   - 已有持久化当前工作区时，只允许 Profile/base 与其一致，不一致返回 `WORKSPACE_ACTIVATION_REQUIRED`；
   - 响应保持兼容；
   - 标记为过渡接口并增加移除条件。
6. 下载端点接受 active 或未过期的 draining session；其他端点只接受 active session；
7. `GET /api/bootstrap` 一次返回当前工作区、session、Profile 摘要和首屏 invoice groups，减少前端启动竞态。

主要影响文件：

- `packages/ro_workbench_api/src/ro_workbench_api/app.py`
- `packages/ro_workbench_api/src/ro_workbench_api/workspace_store.py`
- `packages/ro_workbench_api/src/ro_workbench_api/session_manager.py`
- `packages/ro_workbench_api/tests/test_app.py`

完成条件：

- 新 API 契约测试覆盖正常和错误路径；
- 旧 API 测试继续通过；
- 路由层只负责协议转换和调用服务，不包含客户业务条件。

执行记录（2026-08-07）：

- `app.py` 新增 Profile、Workspace CRUD、两种路径检测、activate 和 bootstrap 端点；响应字段与 Phase 4.5 `WorkspaceService` 契约对齐；
- Workspace API 通过惰性 runtime 接入 `WorkspaceStore` 和 `SessionManager`，测试可用 `RO_WORKBENCH_CONFIG_DIR` 注入隔离配置目录；
- bootstrap 成功时返回当前 workspace、session、PO 列表、invoice groups 和 Profile 摘要；恢复失败时保留持久化 current 并返回稳定 activation error；
- 旧 `/api/session/open` 保留为临时 RO 兼容入口：存在持久化 current 时拒绝不一致的 Profile/base，并返回 `WORKSPACE_ACTIVATION_REQUIRED`；
- PO/Invoice/预览/导出/编辑在提供新 session 时以 session 的 base/context 为准，客户端重复提交的 `base_file` 不再覆盖 session 身份；下载允许 active 或 draining session；
- 新增 5 个工作区 API 契约测试，旧 `test_app.py` 全部通过；完成该任务时全量后端测试为 503 个，ruff、format 和 mypy 均通过。

### 6.9 Task 5.8：为 CLI 增加显式 Profile ✅

目标：CLI 可选择 Profile，但不依赖 GUI 当前工作区。

任务：

1. 增加 `--profile <profile_id>`，缺省为 `ro`；
2. CLI 使用 `GenerationContext(profile, base_file)` 调用核心包；
3. 未知 Profile 继续遵守稳定退出码：参数问题为 `2`，业务阻断为 `1`；
4. `--json` 模式 stdout 仍只输出 JSON；
5. 现有不带 `--profile` 的命令和自动化脚本无需修改。

主要影响文件：

- `packages/ro_generator/src/ro_generator/cli.py`
- `packages/ro_generator/tests/test_cli.py`

完成条件：

- 默认 RO CLI 输出与基线一致；
- CLI 不读取工作区 JSON 或当前工作区状态。

执行记录（2026-08-07）：

- `ro-generate` 新增 `--profile <profile_id>`，缺省为 `ro`；通过默认 Profile 注册表解析，不读取 `WorkspaceStore` 或 GUI 当前工作区；
- 每次 CLI 调用都创建 `GenerationContext(profile, base_file)` 并显式传给核心 `generate()`，保持脚本可重复且让 Profile 身份进入核心执行边界；
- 未知 Profile 输出 `PROFILE_NOT_FOUND` 并返回参数错误退出码 2；生成过程中的业务阻断仍返回 1；
- 新增默认 RO、显式 context、未知 Profile 和 JSON stdout 回归测试；全量 Python 测试当前为 506 个，ruff、format 和 mypy 均通过。

### 6.10 Phase 5 出口门槛 ✅

进入 Phase 6 前必须同时满足：

- RO 核心、CLI、API 全量测试通过；
- Profile、WorkspaceStore、SessionManager、缓存隔离测试通过；
- 新工作区 API 契约已冻结；
- 旧前端仍能通过兼容 API 完成 RO 主流程；
- `ruff`、`mypy` 和前端 build 通过；
- 源码运行和 PyInstaller 资源定位均验证成功；
- 设计文档与实际 API 差异已回写，Phase 6 任务已据此复核。

执行记录（2026-08-08）：

- `uv run pytest packages/ro_generator packages/ro_workbench_api -q`：506 个 Python 用例通过；
- `cd frontend && pnpm run type-check`、`pnpm run build`：通过；`pnpm run test:e2e`：25 个 Playwright 场景通过；
- PyInstaller macOS 构建成功，构建清单包含 `customer_profiles/ro` 的 manifest、schema、workbook、mapping，以及 `frontend/dist`；源码 `resource_root/profile_root/find_profile_root` 断言通过；
- Phase 4.5 的 `WorkspaceService` 契约与 Phase 5 API 差异已确认：bootstrap 成功时额外返回 `workspace`、`po_list`、`invoices`，无当前工作区时这些字段为空/缺省；旧业务端点继续通过 `X-Session-Id` 路由，重复提交的 `base_file` 仅保留兼容性。

## 7. Phase 6：真实 API 接入与发行（实施中）

进入条件：

- Phase 5 已完成并冻结工作区 API；
- 实际 API 与 Phase 4.5 的 `WorkspaceService` 契约差异已经记录；
- Phase 4.5 的交互流程已经确认，不再进行第二套页面设计。

目标：

- 新增真实 HTTP `WorkspaceService`，替换 mock adapter；
- 将工作区 session 与现有 PO、票据组、编辑、预览和导出状态原子接线；
- 完成旧 `ro-workbench-base-path` 的幂等迁移；
- 完成跨 session 下载、失败恢复和重启恢复；
- 扩充真实后端 Playwright 场景并完成 PyInstaller 打包验收；
- 更新用户、产品、UI 和工程文档。

约束：

- 不重写 Phase 4.5 已确认的工作区组件；
- 允许删除 `workspace.mock.ts` 或仅保留为测试 fixture；
- 如果实际 API 迫使交互变化，先回写设计和 service contract，再修改组件；
- 以下先记录 Task 6.0；后续任务在本任务验收后按实际结果追加。

### 7.1 Task 6.0：接入真实 HTTP WorkspaceService ✅

目标：让正式工作台使用 Phase 5 的 HTTP 工作区 API，保留 `workspace-prototype=1` 作为交互评审 mock 开关。

任务：

1. 新增 `frontend/src/services/workspace.http.ts`，实现 Profile/Workspace CRUD、路径检测、activate 和 bootstrap；统一把 FastAPI `detail.code/detail.message` 转成 `WorkspaceServiceError`；
2. 正式模式由 `TopBar` 配置 HTTP service，原型查询参数继续配置 `MockWorkspaceService`；
3. bootstrap 或 activate 成功后，把 session、Profile/base 身份、PO 列表和 Invoice 列表一次性接入 `workbench` store；切换失败不清空旧页面；
4. 对旧 `ro-workbench-base-path` 执行幂等迁移：只有工作区创建和首次激活都成功才删除旧 localStorage key，失败时保留并打开工作区设置；
5. 保持旧 `/api/session/open` 和当前 RO E2E 流程可用，确保真实工作区接入不改变单据检查、预览、编辑和导出请求的 session header。

主要文件：

- `frontend/src/services/workspace.http.ts`
- `frontend/src/services/workspace.ts`
- `frontend/src/stores/workspace.ts`
- `frontend/src/stores/workbench.ts`
- `frontend/src/components/layout/TopBar.vue`

完成条件：

- 正式模式不再默认读取 mock；原型开关仍可重复演示失败回滚；
- activate/bootstrap 返回的 session 能驱动现有 PO/Invoice、预览、编辑、导出流程；
- 旧 localStorage 迁移成功/失败语义符合设计文档；
- type-check、build、现有 Playwright 和 Python 回归均通过。

执行记录（2026-08-08）：

- 新增 `HttpWorkspaceService`，覆盖全部 `/api/profiles`、`/api/workspaces*` 和 `/api/bootstrap` 契约；
- `TopBar` 正式模式切换为 HTTP service，保留 `?workspace-prototype=1` mock 模式；bootstrap/activate 后通过 `workbench.adoptWorkspaceSession()` 原子替换 base、session、PO 和 Invoice 状态；
- 实现旧 `ro-workbench-base-path` 创建 RO 工作区并激活的迁移，失败时不删除旧 key；
- 修复 session 接线回归：`openSession` 必须在读取 `/api/invoices` 前立即写入 `X-Session-Id`，否则后端返回 422 且 PO 列表为空；
- 前端 type-check、build 和 25 个 Playwright 场景通过。

### 7.2 Task 6.1：当前工作区修改后的重新激活与重启恢复 ✅

目标：避免稳定的 `workspace_id` 掩盖已修改的 Profile/base 配置，确保旧 session、当前配置和 bootstrap 恢复始终绑定同一身份。

任务：

1. 后端 bootstrap 比较 active session 的 `workspace_id`、`profile_id` 和规范化 base 路径，只有三者都一致时才复用现有 snapshot；
2. 修改当前工作区后，API 明确返回 `unchecked` 和“请重新检测并激活”，但不提前切断旧 active session；
3. 新配置有效时，下一次 bootstrap 自动构建新 session，旧 session 进入 draining；
4. 新配置无效时，bootstrap 返回稳定 activation error，旧 session 继续可读，用户修复后可再次激活；
5. 前端 store 增加 `needsActivation` 状态，当前工作区被编辑后显示“待重新激活”，允许重新激活；激活成功后一次性清除该状态并替换工作台 session；
6. 增加 API 与交互回归，覆盖有效修改、无效修改、旧 session 保持和当前工作区重新激活。

主要影响文件：

- `packages/ro_workbench_api/src/ro_workbench_api/app.py`
- `packages/ro_workbench_api/tests/test_workspace_api.py`
- `frontend/src/stores/workspace.ts`
- `frontend/src/components/workspace/WorkspaceSettings.vue`
- `frontend/src/components/workspace/WorkspaceSwitcher.vue`
- `frontend/e2e/workspace-prototype.spec.ts`

完成条件：

- 同一 `workspace_id` 但 Profile/base 已变化时，不能复用旧 session snapshot；
- 保存当前工作区后存在明确且可操作的重新激活入口；
- 激活失败保留旧页面和旧 session，重启 bootstrap 不返回混合身份；
- 针对性 API 测试和工作区交互测试通过。

执行记录（2026-08-08）：

- 新增 `_session_matches_workspace` 身份比较；bootstrap 在当前配置变更后重新激活，失败时返回 `WORKSPACE_FILE_MISSING` 等稳定错误；
- 当前工作区更新响应标记为 `unchecked`，并提示“配置已修改，请重新检测并激活”；
- 前端新增 `needsActivation`，工作区设置显示“待重新激活/重新激活”，顶部切换器同步提示；
- API 定向回归 16 个用例通过，工作区原型 Playwright 3 个场景通过，包含当前工作区重新激活。
- 全量回归更新为 508 个 Python 用例和 26 个 Playwright 场景；前端 build、ruff、format、mypy 均通过。
- 重新构建 macOS PyInstaller `.app`，清单包含最新 `frontend/dist` 和 `customer_profiles/ro` 资源。

### 7.3 Task 6.2：真实 HTTP Playwright 与发行资源验收 ✅

目标：在不污染默认兼容回归和用户配置的前提下，验证正式 HTTP 工作区入口及刷新恢复，并确认最终前端与 Profile 资源进入发行包。

任务：

1. 增加隔离的临时配置目录启动脚本，供真实 HTTP Playwright 使用；测试进程结束后清理该目录；
2. 增加独立 `workspace-http.spec.ts`，覆盖创建、路径检测、保存、激活、PO 首屏数据和页面刷新后的 bootstrap 恢复；
3. 默认 `pnpm run test:e2e` 排除隔离场景，避免与旧 `/api/session/open` 回归共享持久化 current；通过 `pnpm run test:e2e:http` 显式执行；
4. 重新构建前端和 macOS PyInstaller，核对 `frontend/dist` 与 `customer_profiles/ro` 资源清单。

主要影响文件：

- `frontend/e2e/support/start-workspace-api.mjs`
- `frontend/e2e/workspace-http.spec.ts`
- `frontend/playwright.workspace.config.ts`
- `frontend/playwright.config.ts`
- `frontend/package.json`
- `frontend/README.md`

完成条件：

- 正式 HTTP 场景可在干净配置目录完成首次工作区流程；
- 刷新页面后不依赖 localStorage 旧路径，能通过 bootstrap 恢复当前 workspace、session 和 PO；
- 默认 26 个兼容/原型场景、独立真实 HTTP 场景和发行包资源检查均通过。

执行记录（2026-08-08）：

- `pnpm run test:e2e:http`：1 个真实 HTTP 场景通过；测试使用临时 `RO_WORKBENCH_CONFIG_DIR`，不写入用户配置；
- 默认 `pnpm run test:e2e`：26 个场景通过；`pnpm run build`、Python 508 个用例、ruff、format、mypy 均通过；
- PyInstaller macOS `.app` 构建成功，`EXE-00.toc` 确认包含最新 `frontend/dist/index.html`、JS/CSS 和 `customer_profiles/ro/profile.yaml`。

### 7.4 Task 6.3：统一发行版本元数据与发布检查 ✅

目标：使安装包、Python 包、FastAPI、前端设置页和锁文件使用同一个发布版本，并在 launcher CI 中阻止版本漂移。

任务：

1. 以现有发布流水线声明的 `APP_VERSION=1.1.0` 作为本次发行版本；
2. 将根工作区、`ro-generator`、`ro-workbench-api`、launcher、前端、模块 `__version__`、FastAPI metadata、安装器和 macOS bundle 对齐；
3. 刷新 `uv.lock` 中的本地 workspace 包版本；
4. 新增 `scripts/verify_release_metadata.py`，从 workflow 读取期望版本并检查全部发布入口；
5. 在 `build-launcher.yml` 中构建前执行版本检查。

主要影响文件：

- `pyproject.toml`
- `packages/*/pyproject.toml`
- `packages/*/src/*/__init__.py`
- `packages/ro_workbench_api/src/ro_workbench_api/app.py`
- `frontend/package.json`
- `frontend/src/components/layout/TopBar.vue`
- `packages/ro_workbench_launcher/installer.iss`
- `scripts/verify_release_metadata.py`
- `.github/workflows/build-launcher.yml`

完成条件：

- `uv run python scripts/verify_release_metadata.py` 输出 `release metadata ok: 1.1.0`；
- 版本变更后的 Python、前端、静态检查和真实 HTTP 验收均通过；
- PyInstaller bundle 仍包含最新前端和 Profile 资源。

执行记录（2026-08-08）：

- 根工作区、三个运行时包、前端、模块版本、FastAPI、安装器和 bundle 统一为 `1.1.0`，`uv lock` 已刷新；
- 版本检查脚本通过，launcher CI 已接入；
- 版本变更后的 Python 508 个用例、type-check/build、ruff/format/mypy、真实 HTTP Playwright 1 个场景和 macOS PyInstaller 构建均通过。

## 8. Phase 7：PF Customer Profile 接入 ✅

进入条件：

- Phase 6 已完成并稳定；
- PF 源目录和 workbook 满足设计文档 §20 的接入门槛；
- 已确认新客户与 RO 的差异矩阵。

### 8.1 Task 7.0：核对 PF 数据与模板差异 ✅

输入目录：`/Users/max/work/赛肯单据小程序/Template PF`（仅作为本机业务资料来源，不写入运行时代码）。

已确认：

- base 文件为 `PO RECORD 2026.xlsx`；
- Sheet 为 `DATA BASE TEMPLATE`、`PO RECORD 26`、`new PO template`；
- 新订单 `4500752093`–`4500752098` 只存在于 `new PO template`；
- Category 使用 `Combo`、`Single Rod`、`Single Reel` 文本；
- 2026 出货数量位于数字表头 `2601`–`2612`，由 `INV#` 的 YYMM 选择；
- 当前生效价格位于 `20260612-NEW PO` 三个链段列；
- GS/EMAX 各提供 PI、PO、Invoice、PL，SK/YM 仅提供 PI；
- Invoice 与 PL 是不同 workbook，不能套用 RO 的双 Sheet 合并假设。

### 8.2 Task 7.1：建立 PF Profile、schema 与客户 PO 先行解析 ✅

新增：

```text
customer_profiles/pf/
  profile.yaml
  base_schema.yaml
  templates/
packages/ro_generator/src/ro_generator/profiles/pf.py
```

实现内容：

1. 注册 `pf`，保持 `ro` 为默认 Profile；
2. schema 支持逻辑 Sheet 与实际 Sheet 名分离、数字月份表头；
3. PF Category 文本归一为核心 `1/2/3`；
4. 对尚未进入 `PO RECORD 26` 的客户 PO 构建只用于 PI/PO 的最小快照行；
5. 按 PF 价格版本建立三个链段的价格映射；
6. PF 发票号保持原值，不继承 RO 的 EMAX `-P`；
7. Profile 身份继续贯穿 snapshot、resolver、preview、export 和缓存。

### 8.3 Task 7.2：实现 MOQ 与整箱提醒 ✅

核心模块 `order_constraints.py` 按 PO、SAP 聚合 `new PO template.Order Quantity`：

- 小于 `DATA BASE TEMPLATE.MOQ`：`MOQ_NOT_MET`；
- 不能被 `DATA BASE TEMPLATE.round value` 整除：`FULL_CARTON_NOT_MET`。

两类结果均为 `warning`、`severity: high`，不阻断预览或导出。规则只由 PF Profile 启用，RO 不执行。API 沿用统一 `get_po_issues()` 序列化，前端沿用 `IssueSummaryBar` 展示，不复制业务判断。

### 8.4 Task 7.3：接入并验证 PF 模板/mapping ✅

交付资产：

- PF 共 10 个 `.xlsx` 和 10 份 YAML mapping；
- 所有 mapping 声明 `template_version`、真实 Sheet、表头保护行、样式来源行和预览列标签；
- GS/EMAX 支持 PI、PO、Invoice、PL；SK/YM 支持 PI；
- 当 Invoice/PL mapping 指向同一模板时沿用双 Sheet workbook；PF 指向不同模板时分别渲染并打 ZIP；
- PF PL 根据月度出货数量重算箱数，按 PO record 原订单总量比例换算 N/W、G/W，并按尺寸重算 CBM；
- 发票 cost breakdown 预留区因缺少已批准数据来源而保留为空，不自动生成。

模板副本已清除示例业务值，原始外部目录未被修改。真实输出已逐格检查 PI/PO/Invoice/PL，未发现 Excel 公式错误。

### 8.5 Task 7.4：API、前端与回归验收 ✅

完成内容：

1. `/api/profiles` 返回可用的 `ro`、`pf`；
2. 前端 Profile 列表可选择 PF，并显示“含 MOQ 与整箱提醒”；
3. 新增 Playwright 场景，验证两类提醒的中文文案、Sheet/行/字段和稳定 code；
4. 增加 PF schema、Category、月度数量、客户 PO 先行、提醒、发票号、分离模板 ZIP 和装箱计算测试；
5. 真实 PF 文件验证 49 个产品、157 个 PO、24 个票据组可建快照；6 个新 PO 均为 ready 且提醒为 0；
6. 代表性 GS/EMAX/SK/YM PI/PO 及 GS/EMAX Invoice/PL 均生成成功。

最终回归（2026-08-08）：Python 518 个用例、默认 Playwright 28 个场景、隔离真实 HTTP Playwright 1 个场景全部通过；前端 build、Ruff、format 和 mypy 同时通过。

### 8.6 Phase 7 出口门槛 ✅

- PF 可在工作区中作为独立 Profile 配置并激活；
- 新 PF PO 无需先复制到 `PO RECORD 26` 即可进入 PI/PO 流程；
- MOQ/整箱不合规时只提醒、不误阻断；
- RO 默认 Profile、日期来源、发票后缀和合并 workbook 行为有自动回归保护；
- PF 模板、mapping 和规则均位于独立命名空间；
- Python、前端构建和 Playwright 验收通过。

本阶段目标已实现：

- 新建独立 Profile 资产目录和规则实现；
- 接入 PF schema、模板、mapping、命名和校验；
- 证明 PF 与 RO 可在同一安装包内切换且互不影响；
- 为 PF 建立合成回归并完成真实文件只读验收。

## 9. Phase 8：多客户加固（目标级）

目标：

- 建立 Profile 兼容版本和配置升级策略；
- 增加配置导入/导出及诊断信息；
- 扩充跨客户性能、并发切换和长期运行测试；
- 在确认兼容入口已无使用后，评估移除旧 `/api/session/open`。

按文档增量规则，进入 Phase 8 时再基于 Phase 7 的实际结果细化任务清单。

## 10. 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| Profile | 注册、未知 ID、重复 ID、资产缺失、RO 默认兼容 |
| PF Profile | 实际 Sheet/字段、文本 Category、月度出货、客户 PO 先行、原始发票号 |
| Core | context 显式传递、schema/rules 隔离、RO 生成回归 |
| Cache | Profile + 路径隔离、签名变化、30 分钟 TTL |
| WorkspaceStore | CRUD、原子写、损坏文件、版本迁移、首次启动 |
| Session | 激活/回滚、并发切换、active/draining、1 小时 TTL |
| API | 新端点契约、错误码、旧入口兼容、session 身份校验 |
| CLI | 默认 RO、显式 Profile、JSON stdout、退出码 |
| Frontend 骨架 | service contract、mock 可替换性、设置、切换、失败回滚、繁忙禁用 |
| Frontend 接入 | bootstrap、真实 API、session 原子替换、旧路径迁移 |
| 客户订单提醒 | MOQ、整箱、按 SAP 聚合、RO 不启用、前端展示 |
| Export | 切换前后文件归属、5 分钟下载宽限、过期处理 |
| Package | bundle 资源、用户配置目录、重启恢复、升级保留配置 |

## 11. 提交和回滚策略

建议按以下独立、可回归的提交边界推进：

1. 前端领域类型、store 和 `WorkspaceService` 契约；
2. 正式设置与切换组件；
3. mock adapter、开发入口、交互测试和评审修正；
4. RO 基线测试；
5. Profile 模型和 RO 默认 Profile；
6. RO 资产目录迁移；
7. 核心 context 化和缓存隔离；
8. WorkspaceStore；
9. SessionManager、API 和 CLI Profile；
10. 真实 HTTP adapter、旧配置迁移、E2E 和打包。

每个提交必须保持相应层的测试可运行。不要在一个提交中同时迁移模板、重写 session 并改前端状态。

回滚原则：

- Phase 4.5 只通过开发开关启用 mock，默认 RO 入口保持不变；
- Phase 5/6 期间始终保留默认 RO 和旧 session 兼容入口；
- 工作区 JSON 使用版本号，迁移前保留可恢复副本；
- 激活失败只回滚新 session，不删除用户配置或输出文件；
- 不用“清空所有配置”作为普通错误恢复方式；
- 模板资产迁移出现问题时回滚代码和资产引用这一整体，而不是复制出两套长期漂移的 RO 模板。

## 12. 完成定义

多客户工作区能力只有同时满足以下条件才算完成：

- 用户可在设置中维护工作区及 base 文件；
- 用户可在顶部栏切换，并明确看到当前工作区；
- 切换是后端验证成功后的原子提交；
- session、缓存、预览、编辑、导出和下载均绑定 Profile/workspace；
- 原 RO GUI 和 CLI 业务结果无回归；
- 发行包重启后可恢复当前工作区；
- PF 已通过独立 Profile 接入，没有修改 RO 规则或在 API/前端壳层增加客户业务分支；
- 产品、UI、实施和用户文档均与实际行为一致。
