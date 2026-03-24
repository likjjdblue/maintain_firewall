# 开发历史记录

> 格式说明：每条记录包含 **日期 · 类型 · 摘要**，正文说明背景、决策与影响文件。
> 类型标签：`[FEAT]` 新功能  `[FIX]` Bug 修复  `[DESIGN]` 设计决策

---

## 2026-03-24

### [FEAT] 前端管理页面初始化

**背景**
后端 (`src/backend/server.py`) 与接口文档 (`devdoc/API.md`) 已就绪，需配套 Web 管理界面。

**实现**
- 新建 `src/backend/templates/index.html`，单页应用，纯原生 CSS + JS，无外部依赖。
- `src/backend/server.py` 补充 `render_template` 导入及 `GET /` 路由。

**页面功能覆盖**

| 模块 | 功能 |
|---|---|
| 顶部状态栏 | firewalld 运行状态、版本、默认 Zone |
| 左侧导航 | Zone 列表，点击切换 |
| 概览 Tab | 各类规则数量统计及快览 |
| 端口规则 Tab | 列表 + 新增（支持来源 IP）+ 删除 |
| 服务规则 Tab | 列表 + 新增（下拉选已知服务）+ 删除 |
| 富规则 Tab | 列表 + 新增（原始字符串 / 结构化参数两种模式）+ 删除 |
| 来源地址 Tab | 列表 + 新增 + 删除 |

**涉及文件**
- `src/backend/server.py`
- `src/backend/templates/index.html` *(新建)*

---

### [FIX] 运行时规则无法二次持久化问题

**问题描述**
用户先勾选"仅运行时"添加规则 → 规则写入 runtime，未写入 permanent。
随后希望持久化同一规则时，后端预查询 runtime 状态发现规则已存在，直接返回 **409**，
导致永久化操作永远无法完成。

**根因**
原 `add_port` / `add_service` / `add_rich_rule` / `add_source` 四个接口在执行写入前，
均通过 `--list-*`（不带 `--permanent`，即查询 runtime）做重复检查，
未区分目标作用域是 runtime 还是 permanent。

**方案选型**

| 方案 | 说明 | 结论 |
|---|---|---|
| 分作用域预查询 | 写 runtime 前查 runtime，写 permanent 前查 permanent | 多次查询，性能与稳定性隐患，**否决** |
| `--runtime-to-permanent` 兜底 | runtime 冲突时整体同步 | 全局副作用，会意外持久化临时规则，**否决** |
| **错误驱动 + 精准 permanent 写入** | 尝试写 runtime，冲突时跳过并单独写 permanent | 无预查询，无全局副作用，**采纳** |

**最终逻辑（`apply_rule_cmd`）**

```
1. apply_runtime=True：执行 runtime add
   - 成功 → 继续
   - 失败且 ALREADY_ENABLED 且 apply_permanent=True → 标记 runtime_already_exists，继续
   - 其他失败 → 返回错误

2. apply_permanent=True：执行 permanent add
   - 成功 → 返回成功
   - 失败且 ALREADY_ENABLED：
       · runtime_already_exists 或 apply_runtime=False → 返回 __ALREADY_EXISTS__（调用方 409）
       · 否则（runtime 刚写成功）→ 视为成功
   - 其他失败 → 返回错误
```

**UI 联动变更**

| 变更前 | 变更后 | 说明 |
|---|---|---|
| "仅永久" 复选框 | "永久" 复选框 | 语义改为 runtime + permanent 同时生效 |
| 默认（均不勾选） | 默认仅运行时 | 需显式勾选"永久"才持久化 |
| 请求字段 `permanent_only` | 请求字段 `permanent` | 对应后端 `parse_persistence_flags` 入参变更 |

**涉及文件**

| 文件 | 改动点 |
|---|---|
| `src/backend/server.py` | 新增 `ALREADY_ENABLED_PATTERN`；重写 `parse_persistence_flags`、`apply_rule_cmd`；移除 4 处预查询代码 |
| `src/backend/templates/index.html` | 5 处表单复选框标签、元素 ID、JS 请求字段同步更新 |
