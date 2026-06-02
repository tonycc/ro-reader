# RO 单据工作台

把 `RO DATA BASE.xlsx` 中的 PO 数据装配为 PI、PO、Invoice、Packing List 四类单据。

## 快速开始

### 桌面应用（macOS）

```bash
# 双击 RO Workbench.app 启动
# 浏览器自动打开，点击顶部文件名 → 输入 base 文件路径 → 开始工作
```

首次打开时 macOS Gatekeeper 可能拦截。绕过方法：右键 → 打开，或前往"系统设置 → 隐私与安全性"点击"仍要打开"。

### 命令行工具

```bash
pip install ro-generator

# 单文档装配
ro-generate --base "RO DATA BASE.xlsx" --po 4500030844 \
  --docs invoice --seller "GS PTE" --buyer "EMAX PTE" \
  --invoice-month 2601 --output-dir ./outputs

# JSON 模式（Agent/自动化调用）
ro-generate --input request.json --json

# 四类单据全部装配
ro-generate --base base.xlsx --po 4500030844 \
  --docs pi,po,invoice,pl --invoice-month 2601 --json
```

退出码：0=成功 / 1=阻断错误 / 2=参数错误 / 3=需补充信息。

### 开发环境

```bash
# 安装依赖
uv sync --all-packages
cd frontend && pnpm install

# 运行测试
uv run pytest                        # 后端
cd frontend && pnpm run build        # 前端构建
cd frontend && pnpm run test:e2e     # E2E

# 启动开发服务器
uv run uvicorn ro_workbench_api.app:app --reload --port 54321  # 后端
cd frontend && pnpm run dev           # 前端 (http://localhost:5173)
```

## 架构

```
ro_generator (核心包) → CLI | FastAPI 后端 → Vue 3 前端 → PyInstaller 启动器
```

业务规则只在 `packages/ro_generator/` 中；CLI、后端、前端都是薄壳。

## 模板矩阵

| 主体 | PI | PO | Invoice | PL |
|---|:-:|:-:|:-:|:-:|
| GS PTE | ✅ | ✅ | ✅ | ✅ |
| EMAX PTE | ✅ | ✅ | ✅ | ✅ |
| SK/YM | ✅ | ❌ | ✅ | ✅ |

每个模板配一份 YAML 映射（`templates/<entity>/mappings/<doc>.yaml`），模板版式变化只改 YAML。

## 文档

- `docs/product/` — 产品方案（权威产品决策）
- `docs/development/` — UI 设计、实施指南
- `CLAUDE.md` — Claude Code 协作指引

## 技术栈

Python 3.11+ / openpyxl / FastAPI / Vue 3 + TypeScript / Pinia / SheetJS / PyInstaller
