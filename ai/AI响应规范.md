# AI 响应规范

## 1. 目标

本文档用于统一建筑能源智能管理系统中 AI 接口的响应方式，降低以下成本：

- 前端针对不同 AI 接口重复写渲染逻辑
- MCP 对不同 AI 接口重复做结构适配
- 后端为每个 AI 接口各自维护一套输出习惯
- Prompt 调整后响应结构不稳定

本文档只规范 **AI 接口响应结构**，不约束业务查询接口。

## 2. 总体原则

### 2.1 统一基础骨架，不统一成单一大结构体

所有 AI 接口应统一基础响应骨架，但不要求所有接口都返回完全相同的字段集合。

换言之：

- 要统一的是通用字段
- 不要强行让每个接口都返回 `answer`、`steps`、`highlights`、`reasons`

### 2.2 业务字段按场景裁剪

不同 AI 接口根据用途选择扩展字段：

- 问答类：适合 `answer`
- 运维指导类：适合 `steps`
- 异常分析类：适合 `reasons`
- 报表总结类：适合 `highlights`、`suggestions`

### 2.3 输出必须适合页面渲染和 MCP 编排

AI 接口返回结果必须满足：

1. 前端可直接拆成卡片或区块渲染
2. MCP 可继续拿结果做下一步调用
3. 结果具备基本可解释性

## 3. 基础响应骨架

所有 AI 接口建议统一包含以下基础字段：

```json
{
  "summary": "一句话结论",
  "evidence": [],
  "actions": [],
  "risk_notice": "",
  "meta": {}
}
```

### 3.1 基础字段定义

#### `summary`

- 类型：`string`
- 含义：本次 AI 响应的一句话摘要
- 要求：
  - 必填
  - 尽量简洁
  - 面向页面标题或首行展示

#### `evidence`

- 类型：`array`
- 含义：支撑当前结论的证据
- 要求：
  - 建议返回数组，允许为空
  - 用于前端展示“依据来源”
  - 用于 MCP 后续可信度判断

#### `actions`

- 类型：`array`
- 含义：建议用户下一步可执行动作
- 要求：
  - 建议返回数组，允许为空
  - 每个动作应可映射到页面跳转或业务接口

#### `risk_notice`

- 类型：`string`
- 含义：风险提示、置信边界、人工确认提示
- 要求：
  - 可为空字符串
  - 涉及推断、估计、规则不完备时应明确提示

#### `meta`

- 类型：`object`
- 含义：补充元数据
- 要求：
  - 可为空对象
  - 存放非核心展示字段
  - 不应用于承载主要业务结论

## 4. 通用子结构定义

### 4.1 `evidence` 结构

```json
{
  "type": "knowledge",
  "source": "冷机运维手册/报警章节",
  "snippet": "高压报警常见原因包括冷却水流量不足、冷凝器污堵等。"
}
```

字段说明：

- `type`
  - 类型：`string`
  - 枚举建议：
    - `knowledge`
    - `data`
    - `rule`
    - `graph`

- `source`
  - 类型：`string`
  - 含义：来源名称

- `snippet`
  - 类型：`string`
  - 含义：关键证据摘要

### 4.2 `actions` 结构

```json
{
  "label": "查看能耗时序",
  "target": "energy_series",
  "target_id": "Panther_lodging_Dean"
}
```

字段说明：

- `label`
  - 类型：`string`
  - 含义：前端按钮或动作文案

- `target`
  - 类型：`string`
  - 含义：动作目标
  - 建议是页面标识、接口标识或业务动作标识

- `target_id`
  - 类型：`string`
  - 含义：可选目标 ID

### 4.3 `reasons` 结构

用于异常分析类接口。

```json
{
  "title": "夜间基础负载偏高",
  "description": "该时段电耗未随正常作息回落，可能存在设备持续运行情况。",
  "confidence": 0.82
}
```

字段说明：

- `title`
  - 原因标题

- `description`
  - 原因说明

- `confidence`
  - 类型：`number`
  - 建议范围：`0 ~ 1`

## 5. 扩展字段规范

以下字段不要求所有 AI 接口都返回，只在适合的场景使用。

### 5.1 `answer`

- 类型：`string`
- 用途：完整自然语言回答
- 适用接口：
  - 通用问答
  - 文档问答
  - 知识解释

### 5.2 `steps`

- 类型：`array[string]`
- 用途：分步骤操作建议
- 适用接口：
  - 运维指导
  - 故障排查

### 5.3 `highlights`

- 类型：`array[string]`
- 用途：重点摘要
- 适用接口：
  - 报表总结
  - 周报/月报总结

### 5.4 `suggestions`

- 类型：`array[string]`
- 用途：建议项
- 适用接口：
  - 节能建议
  - 报表建议

### 5.5 `reasons`

- 类型：`array<object>`
- 用途：原因候选列表
- 适用接口：
  - 异常分析
  - 告警解释

## 6. 各类 AI 接口推荐结构

### 6.1 通用问答类

适用接口：

- `/ai/qa`

推荐结构：

```json
{
  "summary": "冷机高压报警通常表示冷凝侧压力异常升高。",
  "answer": "常见原因包括冷却水流量不足、冷凝器污堵、环境温度过高等。",
  "evidence": [
    {
      "type": "knowledge",
      "source": "冷机运维手册/报警章节",
      "snippet": "高压报警常见原因包括..."
    }
  ],
  "actions": [
    {
      "label": "查看运维指导",
      "target": "ai_ops_guide"
    }
  ],
  "risk_notice": "仅依据知识库回答，现场仍需人工确认。",
  "meta": {}
}
```

### 6.2 查数辅助类

适用接口：

- `/ai/query-assistant`

推荐结构：

```json
{
  "summary": "已识别为单建筑近 7 天电耗趋势查询。",
  "query_intent": {
    "building_id": "Panther_lodging_Dean",
    "meter": "electricity",
    "time_range": {
      "start": "2026-03-23T00:00:00+08:00",
      "end": "2026-03-30T00:00:00+08:00"
    }
  },
  "evidence": [],
  "actions": [
    {
      "label": "执行能耗时序查询",
      "target": "/energy/series"
    }
  ],
  "risk_notice": "",
  "meta": {
    "recommended_endpoint": "/energy/series",
    "recommended_http_method": "GET",
    "recommended_query_params": {
      "building_id": "Panther_lodging_Dean",
      "meter": "electricity"
    }
  }
}
```

### 6.3 运维指导类

适用接口：

- `/ai/ops-guide`

推荐结构：

```json
{
  "summary": "建议先检查控制逻辑，再核对负载需求和传感器状态。",
  "steps": [
    "检查启停控制阈值配置",
    "检查负载需求是否异常波动",
    "核对压力和流量传感器",
    "检查设备本体与继电控制"
  ],
  "evidence": [
    {
      "type": "knowledge",
      "source": "泵组运维手册/启停异常章节",
      "snippet": "频繁启停通常优先检查控制逻辑和负载波动。"
    }
  ],
  "actions": [
    {
      "label": "查看相关知识",
      "target": "knowledge_detail"
    }
  ],
  "risk_notice": "涉及现场操作时需遵守安全规范。",
  "meta": {}
}
```

### 6.4 异常分析解释类

适用接口：

- `/ai/analyze-anomaly`

推荐结构：

```json
{
  "summary": "该异常更可能由夜间基础负载持续偏高引起。",
  "reasons": [
    {
      "title": "夜间基础负载偏高",
      "description": "与历史同期相比，夜间时段电耗未明显回落。",
      "confidence": 0.82
    },
    {
      "title": "空调系统持续运行",
      "description": "存在运行策略未切换或设备未停机的可能。",
      "confidence": 0.64
    }
  ],
  "evidence": [
    {
      "type": "data",
      "source": "energy.anomaly_analysis",
      "snippet": "夜间实际值较基线高出 18%"
    },
    {
      "type": "knowledge",
      "source": "运维知识库/夜间负载异常章节",
      "snippet": "夜间基础负载偏高常见于设备持续运行。"
    }
  ],
  "actions": [
    {
      "label": "查看能耗时序",
      "target": "energy_series"
    },
    {
      "label": "查看运维指导",
      "target": "ai_ops_guide"
    }
  ],
  "risk_notice": "当前结论基于样本数据和规则推断，仅供辅助判断。",
  "meta": {}
}
```

### 6.5 报表总结类

适用接口：

- `/ai/report-summary`

推荐结构：

```json
{
  "summary": "本周该建筑整体电耗较上周上升，夜间基础负载偏高为主要问题。",
  "highlights": [
    "本周总电耗较上周上升 8.2%",
    "夜间负载连续三天高于历史同期",
    "周中出现一次明显异常波动"
  ],
  "suggestions": [
    "排查夜间运行策略",
    "关注空调系统停机时段",
    "复核异常时段设备状态"
  ],
  "evidence": [
    {
      "type": "data",
      "source": "weekly_energy_summary",
      "snippet": "夜间均值高于历史同期"
    }
  ],
  "actions": [
    {
      "label": "导出报告",
      "target": "report_export"
    }
  ],
  "risk_notice": "",
  "meta": {}
}
```

## 7. 字段使用约束

### 7.1 必填字段

所有 AI 接口建议至少保证以下字段存在：

- `summary`
- `evidence`
- `actions`
- `risk_notice`
- `meta`

其中：

- `evidence` 可以为空数组
- `actions` 可以为空数组
- `risk_notice` 可以为空字符串
- `meta` 可以为空对象

### 7.2 不建议返回 `null`

建议：

- 字符串无值时返回 `""`
- 数组无值时返回 `[]`
- 对象无值时返回 `{}`

原因：

- 前端处理更简单
- MCP 适配更稳定

### 7.3 `confidence` 范围

如果返回 `confidence`，建议统一约束在：

- `0 ~ 1`

不要有的接口返回百分比，有的接口返回小数。

### 7.4 `evidence` 最少返回策略

建议：

- 能返回证据时必须返回
- 如果当前阶段确实没有可靠证据，可返回空数组，但不要伪造来源

## 8. 不推荐的设计

### 8.1 不推荐所有接口都共用同一个大结构体

不推荐做成：

```json
{
  "summary": "...",
  "answer": "...",
  "steps": [],
  "highlights": [],
  "suggestions": [],
  "reasons": [],
  "evidence": [],
  "actions": [],
  "risk_notice": "",
  "meta": {}
}
```

原因：

- 字段大量空置
- 文档冗余
- 模型输出不稳定
- 前端容易误以为所有字段都应该展示

### 8.2 不推荐省略基础骨架

如果每个 AI 接口都返回完全不同的结构：

- 前端代价高
- MCP 编排复杂
- 后续难维护

## 9. 正式约定

最终约定如下：

1. 所有 AI 接口统一基础响应骨架
2. 基础骨架固定为：
   - `summary`
   - `evidence`
   - `actions`
   - `risk_notice`
   - `meta`
3. 扩展字段按接口类型裁剪
4. 不使用单一大而全结构体作为所有 AI 接口的唯一返回模型
5. 所有 AI 接口的 OpenAPI schema 应按本规范设计
