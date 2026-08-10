# 文档索引

仓库只保留反映当前实现的长期文档。已完成的一次性设计稿和实施计划在结论合并后删除，历史过程通过 Git 查看。

## 使用与产品

- [`../README.md`](../README.md)：安装、工作台、CLI、API 和开发入口。
- [`product/ro-document-generator-product-plan.md`](product/ro-document-generator-product-plan.md)：当前产品范围、业务流程、输出和 roadmap。

## 已确认、分阶段实施

- [`product/multi-customer-workspace-design.md`](product/multi-customer-workspace-design.md)：多客户 Profile、工作区、切换事务和兼容设计。
- [`development/multi-customer-workspace-implementation-plan.md`](development/multi-customer-workspace-implementation-plan.md)：Phase 4.5 前端骨架和 Phase 5 核心/后端的开发顺序、文件边界与验收门槛。

Phase 4.5–6 的多工作区基础已完成；Phase 7 已接入 PF Profile，包括独立 schema、10 份模板/mapping、客户 PO 先行、月度出货数量、MOQ/整箱提醒及 PF Invoice/PL 打包。下一阶段 Phase 8 仍只保留目标级描述。

## 开发

- [`development/implementation-guide.md`](development/implementation-guide.md)：代码结构、数据流、修改流程、测试和发布。
- [`development/ro-document-workbench-ui-design.md`](development/ro-document-workbench-ui-design.md)：当前 Vue UI、状态和交互边界。

## 字段与模板

- [`单据模板字段取值规则汇总.md`](单据模板字段取值规则汇总.md)：各业务单据字段来源基准。
- [`development/agent-field-fix-playbook.md`](development/agent-field-fix-playbook.md)：字段问题标准排查与修复步骤。
- [`development/field-fix-case-library.md`](development/field-fix-case-library.md)：已验证的字段修复案例。

## 维护规则

- 代码、schema 或测试与文档冲突时，先确认实际实现和产品意图，再在同一变更中同步文档。
- 不在长期文档中把 roadmap 写成已实现能力。
- 临时 spec/plan 应放在工作分支；功能完成后提炼长期结论并删除临时文件。
- 修改支持单据、Sheet、CLI、API、mapping、输出命名、PDF 或 UI 时，至少检查本索引列出的相关文档。
