# AI接口总览

## 当前保留的 AI 接口

| 接口 | 方法 | 作用 | 优先级 |
|---|---|---|---|
| `/ai/query-assistant` | POST | 解析自然语言查询意图，推荐后续 energy 接口 | P1 |
| `/ai/analyze-anomaly` | POST | 基于异常检测结果生成候选原因、证据和建议动作 | P0 |
| `/ai/anomaly-feedback` | POST | 保存用户对异常候选原因的确认和评分 | P0 |

---

## 1. `POST /ai/query-assistant`

### 作用

把自然语言问题解析成结构化查询意图，并推荐后续应调用的 energy 接口。

这个接口不执行真实查询，只返回：

- `query_intent`
- `recommended_endpoint`
- `recommended_http_method`
- `recommended_query_params`
- `warnings`

### 请求示例

```json
{
  "question": "查 Bear_assembly_Angel 最近7天电耗趋势",
  "current_time": "2026-04-01T10:00:00+08:00"
}
```

### 返回示例

```json
{
  "summary": "已将问题解析为 /energy/trend 的查询意图。",
  "query_intent": {
    "building_ids": ["Bear_assembly_Angel"],
    "site_id": null,
    "meter": "electricity",
    "time_range": {
      "start": "2026-03-25T10:00:00+08:00",
      "end": "2026-04-01T10:00:00+08:00"
    },
    "granularity": "day",
    "aggregation": null,
    "metric": null,
    "limit": null
  },
  "recommended_endpoint": "/energy/trend",
  "recommended_http_method": "GET",
  "recommended_query_params": {
    "building_ids": ["Bear_assembly_Angel"],
    "meter": "electricity",
    "start_time": "2026-03-25T10:00:00+08:00",
    "end_time": "2026-04-01T10:00:00+08:00",
    "granularity": "day"
  },
  "warnings": [],
  "meta": {
    "generated_at": "2026-04-01T10:00:01+08:00",
    "model": "qwen3.5-plus",
    "used_fallback": false
  }
}
```

### 推荐 endpoint 白名单

`recommended_endpoint` 只能从以下值中选择：

- `/energy/query`
- `/energy/trend`
- `/energy/compare`
- `/energy/rankings`
- `/energy/weather-correlation`
- `/energy/anomaly-analysis`

---

## 2. `POST /ai/analyze-anomaly`

### 作用

对单次建筑能耗异常进行 AI 分析，返回：

- `summary`
- `answer`
- `candidate_causes`
- `evidence`
- `actions`
- `feedback_prompt`

### 返回结构要求

- `candidate_causes` 必须有稳定的 `cause_id`
- `candidate_causes` 数量控制在 `2-5`
- `evidence` 必须能支撑主要结论
- `actions` 只能推荐真实存在的后续系统动作
- `risk_notice` 必须明确说明“这是诊断建议，不是已确认故障”

### `actions.target` 白名单

`actions.target` 不是文件路径，而是一个“后续动作标识”。

当前阶段只允许模型输出以下目标：

- `energy_trend`
- `energy_compare`
- `energy_weather_correlation`
- `energy_anomaly_analysis`
- `/ai/anomaly-feedback`

系统通过环境变量控制白名单：

```powershell
$env:AI_ALLOWED_ACTION_TARGETS='energy_trend,energy_compare,energy_weather_correlation,energy_anomaly_analysis,/ai/anomaly-feedback'
```

### 设计原则

- prompt 中明确告诉模型允许的 `actions.target`
- 后端 normalize 阶段再次做白名单过滤
- fallback 默认动作也必须经过同一份白名单过滤

---

## 3. `POST /ai/anomaly-feedback`

### 作用

保存用户对本次异常分析的反馈，用于后续历史反馈检索和经验复用。

### 请求核心字段

- `analysis_id`
- `building_id`
- `meter`
- `time_range`
- `selected_cause_id`
- `selected_score`
- `candidate_feedbacks`
- `comment`
- `resolution_status`

### 返回核心字段

- `feedback_id`
- `analysis_id`
- `stored`
- `selected_cause`
- `meta`

---

## 4. 推荐实现顺序

### P0

1. `/ai/analyze-anomaly`
2. `/ai/anomaly-feedback`

### P1

1. `/ai/query-assistant`

---

## 5. 当前闭环

```text
/energy/anomaly-analysis
  -> /ai/analyze-anomaly
  -> /ai/anomaly-feedback
  -> 历史反馈检索
  -> 下一次 /ai/analyze-anomaly
```
