# AI异常分析闭环设计

## 1. 目标

异常分析接口不能只返回一段自然语言结论。它需要同时支持：

- 给前端展示候选原因列表
- 让用户选择最可能原因并打分
- 让后端把本次诊断记录沉淀为经验样本
- 让下一次分析时可检索历史相似反馈

因此，`POST /ai/analyze-anomaly` 的响应需要统一成“结论 + 候选原因 + 证据 + 后续动作”的结构。

---

## 2. 推荐响应结构

```json
{
  "analysis_id": "ana_20260331_0001",
  "summary": "检测到明显异常，当前更可能与冷负荷异常升高或设备效率下降有关。",
  "status": "needs_confirmation",
  "answer": "本次异常主要表现为目标时段电耗显著高于基线，且天气因素只能部分解释波动。建议优先排查冷负荷变化、设备效率和计量异常。",
  "candidate_causes": [
    {
      "cause_id": "cooling_load_rise",
      "title": "冷负荷异常升高",
      "description": "气温升高且冷量需求明显增加，导致目标时段电耗同步上升。",
      "confidence": 0.78,
      "rank": 1,
      "recommended_checks": [
        "检查冷机负载率是否持续高位",
        "检查冷冻水供回水温差是否异常",
        "检查控制策略是否存在过度供冷"
      ],
      "evidence_ids": [
        "evi_001",
        "evi_002"
      ]
    },
    {
      "cause_id": "efficiency_drop",
      "title": "设备效率下降",
      "description": "单位产出耗能偏高，疑似设备运行效率下降。",
      "confidence": 0.63,
      "rank": 2,
      "recommended_checks": [
        "检查关键设备近期运行工况",
        "核对冷量与耗电比值是否异常",
        "检查过滤器、换热器或泵组状态"
      ],
      "evidence_ids": [
        "evi_003"
      ]
    },
    {
      "cause_id": "meter_bias",
      "title": "计量或传感器异常",
      "description": "曲线局部波动不符合物理规律，存在表计漂移或采集异常的可能。",
      "confidence": 0.32,
      "rank": 3,
      "recommended_checks": [
        "核对原始采集点位是否缺失或突变",
        "检查表计校准记录",
        "检查采集链路是否稳定"
      ],
      "evidence_ids": [
        "evi_004"
      ]
    }
  ],
  "highlights": [
    "异常点数量为 73",
    "最大偏离率为 71.52%",
    "天气因素只能部分解释波动"
  ],
  "evidence": [
    {
      "evidence_id": "evi_001",
      "type": "data",
      "source": "energy_anomaly_analysis",
      "snippet": "2017-01-03 12:00 到 18:00 电耗显著高于基线 71.52%",
      "weight": 0.91
    },
    {
      "evidence_id": "evi_002",
      "type": "weather",
      "source": "energy_weather_correlation",
      "snippet": "气温与电耗存在中等相关，但不足以单独解释本次异常",
      "weight": 0.67
    },
    {
      "evidence_id": "evi_003",
      "type": "rule",
      "source": "ops_rulebook",
      "snippet": "当单位冷量耗电持续偏高时，应优先检查设备效率退化",
      "weight": 0.74
    }
  ],
  "actions": [
    {
      "label": "查看原始趋势",
      "action_type": "open_tool",
      "target": "energy_trend"
    },
    {
      "label": "查看天气相关性",
      "action_type": "open_tool",
      "target": "energy_weather_correlation"
    }
  ],
  "risk_notice": "当前结果属于诊断建议，不应直接视为已确认故障。",
  "feedback_prompt": {
    "enabled": true,
    "message": "请从候选原因中选择最可能的一项，并对本次建议进行评分。",
    "allow_score": true,
    "allow_comment": true
  },
  "meta": {
    "building_id": "Bear_assembly_Angel",
    "meter": "electricity",
    "time_range": {
      "start": "2017-01-01T00:00:00+00:00",
      "end": "2017-01-07T00:00:00+00:00"
    },
    "baseline_mode": "overall_mean",
    "generated_at": "2026-03-31T20:00:00+08:00",
    "model": "qwen3.5:35b"
  }
}
```

---

## 3. 字段说明

### 3.1 顶层字段

| 字段 | 类型 | 是否必需 | 说明 |
|---|---|---|---|
| `analysis_id` | string | 是 | 本次分析唯一 ID，用于后续反馈入库和经验追踪 |
| `summary` | string | 是 | 一句话结论，供页面卡片和消息摘要使用 |
| `status` | string | 是 | 建议固定为 `needs_confirmation` / `resolved` / `low_confidence` |
| `answer` | string | 是 | 完整解释文本 |
| `candidate_causes` | array | 是 | 候选原因列表，至少 2 个，最多 5 个 |
| `highlights` | array[string] | 否 | 关键观察点 |
| `evidence` | array | 是 | 支撑本次判断的证据 |
| `actions` | array | 否 | 前端可直接跳转或触发的动作 |
| `risk_notice` | string | 是 | 风险提示 |
| `feedback_prompt` | object | 是 | 前端是否应展示反馈入口 |
| `meta` | object | 是 | 与本次分析绑定的上下文元信息 |

### 3.2 `candidate_causes`

每个候选原因建议包含：

| 字段 | 类型 | 是否必需 | 说明 |
|---|---|---|---|
| `cause_id` | string | 是 | 稳定原因 ID，供反馈和统计使用 |
| `title` | string | 是 | 原因标题 |
| `description` | string | 是 | 原因解释 |
| `confidence` | number | 是 | 0 到 1 之间的置信度 |
| `rank` | integer | 是 | 当前候选排序 |
| `recommended_checks` | array[string] | 否 | 建议排查动作 |
| `evidence_ids` | array[string] | 否 | 命中的证据 ID 列表 |

### 3.3 `evidence`

建议统一为：

| 字段 | 类型 | 是否必需 | 说明 |
|---|---|---|---|
| `evidence_id` | string | 是 | 证据唯一 ID |
| `type` | string | 是 | `data` / `weather` / `rule` / `knowledge` / `history_case` |
| `source` | string | 是 | 来源模块 |
| `snippet` | string | 是 | 可读证据摘要 |
| `weight` | number | 否 | 证据权重，0 到 1 |

---

## 4. 设计约束

### 4.1 `candidate_causes` 必须稳定可反馈

候选原因不能只是一段自然语言。必须带稳定的 `cause_id`，否则：

- 前端无法提交“我选了哪一个”
- 后端无法统计哪个原因经常被确认
- 历史经验无法沉淀

### 4.2 `analysis_id` 必须由后端生成

前端和用户反馈都要引用 `analysis_id`。后续反馈表应以它为主关联键之一。

### 4.3 原因数量不要过多

建议：

- 最少 2 个
- 最多 5 个
- 默认 3 个最佳

原因太多会稀释用户判断，也不利于后续统计。

### 4.4 置信度是排序参考，不是概率承诺

`confidence` 只用于排序和 UI 展示，不代表严格概率。前端不能把它表述成“系统已经确认”。

---

## 5. 前端交互要求

前端接到这个结构后，应至少支持：

1. 展示一句话结论和完整解释
2. 展示候选原因列表
3. 让用户选择“最可能原因”
4. 允许用户给候选原因或本次分析打分
5. 可选填写备注

建议交互：

- 单选：`candidate_causes`
- 评分：`1-5`
- 备注：可选文本

---

## 6. 与下一步的关系

这一步结构定义完成后，下一步要基于以下字段设计反馈接口：

- `analysis_id`
- `candidate_causes[].cause_id`
- `meta.building_id`
- `meta.meter`
- `meta.time_range`

下一步应定义：

- `POST /ai/anomaly-feedback`
- 请求体结构
- 反馈表结构

