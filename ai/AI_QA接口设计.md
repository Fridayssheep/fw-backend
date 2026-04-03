# `/ai/qa` 接口设计

## 1. 接口定位

`/ai/qa` 不是单一的知识库问答接口。

它的角色应当是：

- 前端统一的“总览式 AI 问答入口”
- 用户可以在这里提出知识问答、数据查询、异常分析、混合型问题
- 后端 AI 编排层负责决定内部该调用哪类能力
- 前端只消费统一响应，不直接感知内部是 RAG、异常分析还是查询助手

换句话说：

- `RAGFlow` 是内部能力
- `MCP tools` 是内部能力
- `/ai/qa` 是对前端暴露的统一接口

---

## 2. 设计目标

这个接口需要同时满足 4 件事：

1. 前端始终只对接一个问答入口
2. 后端可以按问题类型选择不同工具
3. 前端仍然可以显示知识库或数据证据
4. 返回结构足够稳定，后续新增能力时不破坏前端

---

## 3. 请求结构

```json
{
  "question": "这台泵对环境温度和海拔有什么要求？",
  "session_id": "optional-frontend-session-id",
  "context": {
    "page": "device_detail",
    "building_id": "Bear_assembly_Angel",
    "device_id": "pump_sls_001",
    "anomaly_id": null,
    "meter": "electricity",
    "time_range": {
      "start": "2026-04-01T00:00:00+08:00",
      "end": "2026-04-02T00:00:00+08:00"
    }
  }
}
```

### 字段说明

| 字段 | 是否必填 | 说明 |
|---|---|---|
| `question` | 是 | 用户自然语言问题 |
| `session_id` | 否 | 前端自己的会话标识，只用于前端维持会话，不强绑定上游模型 session |
| `context` | 否 | 当前页面与业务对象上下文，帮助 AI 编排层理解问题 |

### `context` 字段说明

| 字段 | 是否必填 | 说明 |
|---|---|---|
| `page` | 否 | 当前页面标识，例如 `dashboard`、`device_detail`、`anomaly_detail` |
| `building_id` | 否 | 当前建筑 ID |
| `device_id` | 否 | 当前设备 ID |
| `anomaly_id` | 否 | 当前异常 ID |
| `meter` | 否 | 当前表计类型 |
| `time_range` | 否 | 当前页面绑定的时间范围 |

### 约束

- `context` 整体是可选的
- 但如果问题属于“异常/故障分析”，且希望直接给出诊断结论，则至少应提供：
  - `building_id`
  - `meter`
  - `time_range`

---

## 4. 响应结构

```json
{
  "answer": "根据知识库资料，这类泵正常工作时环境温度不超过40℃、海拔高度不高于1000m、相对湿度不超过95%。",
  "question_type": "knowledge",
  "references": {
    "knowledge": [
      {
        "source_type": "knowledge",
        "document_id": "doc_001",
        "document_name": "SLS单级单吸离心泵.pdf",
        "chunk_id": "chunk_001",
        "snippet": "周围环境温度不超过40℃，海拔高度不高于1000m，相对湿度不超过95%。",
        "score": 0.91
      }
    ],
    "data": [],
    "history_cases": []
  },
  "used_tools": [
    {
      "tool_name": "search_domain_knowledge",
      "tool_type": "internal_service",
      "reason": "问题属于知识库检索场景，需要先获取文档证据。"
    }
  ],
  "suggested_actions": [
    {
      "label": "查看知识引用",
      "action_type": "view_reference",
      "target": "knowledge_reference_panel"
    }
  ],
  "meta": {
    "provider": "orchestrated",
    "model": "qwen3.5-plus",
    "generated_at": "2026-04-02T18:00:00+08:00",
    "used_tools_count": 1,
    "has_references": true
  }
}
```

---

## 5. 响应字段语义

### 5.1 `answer`

- 给前端主展示区使用的最终自然语言回答
- 应尽量是“用户能直接看懂并执行下一步”的结果

### 5.2 `question_type`

用于前端和埋点理解这次问题大类。

当前约定值：

- `knowledge`
- `data_query`
- `fault_analysis`
- `mixed`
- `other`

### 5.3 `references`

这是前端展示证据的统一字段。

分为三类：

- `knowledge`
- `data`
- `history_cases`

#### 重要约束

- `references` 是**展示型证据**
- 它不是给 MCP 或别的 AI 继续拼接大上下文用的
- 每条引用都应保持轻量、可读、可直接展示
- 不要把完整原始文档或大量 chunk 原文原样塞回前端

### 5.4 `used_tools`

告诉前端和调试方：

- 本次回答内部到底用了哪些能力
- 每个能力为什么被调用

这个字段主要用于：

- 调试
- 埋点
- 解释性展示

### 5.5 `suggested_actions`

这是给前端的后续动作建议。

前端只负责根据 `target` 做映射，不要求直接理解内部工具。

示例：

- `knowledge_reference_panel`
- `/energy/trend`
- `anomaly_detail`

### 5.6 `meta`

用于记录：

- 本次回答的总体提供方式
- 使用的模型
- 生成时间
- 工具数量
- 是否有证据引用

---

## 6. 问题类型与处理策略

### 6.1 知识型问题

示例：

- “这台泵对环境温度和海拔有什么要求？”
- “COP 是什么意思？”
- “冷机报警代码 E03 一般代表什么？”

处理策略：

1. 调用 `search_domain_knowledge`
2. 获取结构化知识片段
3. 用主模型基于知识片段生成最终回答
4. 把知识片段整理进 `references.knowledge`

### 6.2 数据查询型问题

示例：

- “查 Bear_assembly_Angel 最近7天电耗趋势”
- “本月电耗排行前 5 是谁”
- “看看这栋楼和另一栋楼的电耗对比”

处理策略：

1. 调用 `query_assistant`
2. 生成结构化查询意图
3. 返回推荐接口、参数和后续动作
4. 把该次推荐整理进 `references.data`

当前阶段说明：

- 第一版优先返回“推荐查询”和解释
- 不强行在 `/ai/qa` 里执行所有下游数据接口

### 6.3 异常/故障分析问题

示例：

- “为什么这个建筑昨天晚上报警了？”
- “这次异常更可能是什么原因？”
- “帮我分析一下这段异常波动”

处理策略：

- 如果上下文足够：
  1. 调用 `analyze_anomaly_with_ai`
  2. 直接返回分析结论、证据和建议动作
- 如果上下文不足：
  - 返回明确说明，告诉前端或用户缺什么信息

### 6.4 混合型问题

示例：

- “这次异常是不是和天气有关？顺便给我看看最近趋势”
- “这台泵为什么报警？顺便告诉我说明书里对环境温度有什么要求”
- “这个异常要怎么排查，再帮我看看最近7天电耗趋势”

当前阶段策略：

1. 先识别问题中是否同时包含：
   - 知识诉求
   - 数据诉求
   - 异常/故障分析诉求
2. 命中哪个就执行哪个能力
3. 将多路结果统一汇总成：
   - 一段最终 `answer`
   - 合并后的 `references`
   - 合并后的 `used_tools`
   - 去重后的 `suggested_actions`

当前第一版的能力边界：

- 已支持“知识 + 数据”
- 已支持“知识 + 异常”
- 已支持“数据 + 异常”
- 若问题命中多个维度，则 `question_type = mixed`
- 如果异常分析所需上下文不足，则该部分会返回“信息不足”的说明，但不阻断其他子能力继续返回

---

## 7. 前端如何使用 `references`

前端只需要做两件事：

1. 渲染 `answer`
2. 按类型渲染 `references`

建议展示方式：

- `references.knowledge` -> 文档引用卡片
- `references.data` -> 查询依据 / 图表依据
- `references.history_cases` -> 相似案例卡片

前端不需要：

- 直接调用 RAGFlow
- 理解 MCP 协议
- 拼接大段原始上下文给别的模型

---

## 8. 与 MCP 的边界

### MCP 负责什么

- 提供独立工具能力
- 如 `search_domain_knowledge`
- 如 `energy_trend`
- 如 `energy_anomaly_analysis`

### `/ai/qa` 负责什么

- 统一接收问题
- 做问题分类
- 决定调用哪个工具
- 整理最终回答
- 整理前端可展示的引用

所以：

- MCP 是内部积木
- `/ai/qa` 是外部统一入口

---

## 9. 当前实现边界

当前第一版实现目标是：

- 接口结构先稳定
- 知识问答、数据查询、异常分析三条主路径先跑通
- 前端先能基于统一结构接入

当前不追求一次性解决：

- 完整多工具链式推理
- 完整会话记忆
- 所有混合问题都能一步处理完

这些可以在接口稳定后逐步增强。

---

## 10. 当前结论

`/ai/qa` 的正确定位应当是：

- **统一 AI 编排入口**
- **不是 RAGFlow 聊天接口代理**
- **可以返回知识、数据、历史案例三类证据**
- **前端永远只看统一响应结构**

这就是后续代码实现和前端对接的基准。
