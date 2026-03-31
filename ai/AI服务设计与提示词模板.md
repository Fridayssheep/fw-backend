# AI服务设计与提示词模板

## 1. 分层建议

推荐把 AI 逻辑拆成两层：

```text
app/
  router_ai.py
  schemas.py

ai/backend/
  anomaly_service.py
  feedback_service.py
  query_assistant_service.py
  prompting.py
  llm_client.py
  history.py
  knowledge.py
  config.py
```

职责划分：

- `app/router_ai.py`：HTTP 路由入口
- `app/schemas.py`：请求/响应模型
- `ai/backend/*`：AI 编排、提示词、模型调用、历史反馈检索

---

## 2. `/ai/analyze-anomaly` 内部流程

```text
1. 接收请求
2. 调用 /energy/anomaly-analysis 对应的内部 service
3. 可选调用 /energy/weather-correlation 对应的内部 service
4. 检索知识库
5. 检索历史反馈
6. 组装 prompt
7. 调用 OpenAI-compatible LLM
8. normalize 输出
9. 注入 analysis_id 和 meta
```

### 关键规则

- 当前证据优先于历史反馈
- 历史反馈只能辅助排序，不能覆盖当前证据
- 结果只能写成“候选原因”或“诊断建议”
- `actions.target` 必须经过白名单过滤

---

## 3. `actions.target` 白名单约定

### 语义

`actions.target` 表示后续动作目标标识，不是文件路径。

常见含义：

- `open_tool`：建议调用某个 MCP 工具
- `open_api`：建议调用某个后端接口

### 当前允许值

- `energy_trend`
- `energy_compare`
- `energy_weather_correlation`
- `energy_anomaly_analysis`
- `/ai/anomaly-feedback`

### 环境变量

```powershell
$env:AI_ALLOWED_ACTION_TARGETS='energy_trend,energy_compare,energy_weather_correlation,energy_anomaly_analysis,/ai/anomaly-feedback'
```

### 工程约束

- prompt 必须把允许值显式告诉模型
- normalize 阶段必须丢弃不在白名单中的动作
- fallback 默认动作也必须走同一份白名单

---

## 4. `/ai/analyze-anomaly` Prompt 约束

### System Prompt 原则

- 中文业务语义
- 英文 JSON 字段名
- 明确禁止输出 Markdown 和解释文字
- 明确要求 `candidate_causes`、`evidence`、`actions`、`feedback_prompt`

### User Prompt 必须提供

- 请求参数摘要
- 异常检测摘要
- 天气摘要
- 知识库摘要
- 历史反馈摘要
- 允许的 `actions.target` 列表
- JSON 骨架示例

---

## 5. `/ai/query-assistant` 内部流程

```text
1. 接收自然语言问题
2. 先做本地 heuristic 解析，生成 fallback intent
3. 调用 LLM 做结构化意图提取
4. normalize LLM 输出
5. 推荐现有 energy 接口，不执行真实查询
6. 返回 query_intent + recommended_endpoint + recommended_query_params
```

### 设计目标

- 只负责“理解问题”
- 不负责“执行查询”
- 适合前端和 MCP 共用

### 推荐 endpoint 白名单

- `/energy/query`
- `/energy/trend`
- `/energy/compare`
- `/energy/rankings`
- `/energy/weather-correlation`
- `/energy/anomaly-analysis`

### 路由建议

- 趋势类问题 -> `/energy/trend`
- 对比类问题 -> `/energy/compare`
- 排行类问题 -> `/energy/rankings`
- 天气相关类问题 -> `/energy/weather-correlation`
- 异常排查类问题 -> `/energy/anomaly-analysis`
- 其余明细/聚合类问题 -> `/energy/query`

---

## 6. OpenAI-compatible 调用约定

当前统一按 OpenAI-compatible 接口调用。

环境变量：

```powershell
$env:LLM_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
$env:LLM_API_KEY='your-api-key'
$env:LLM_MODEL='qwen3.5-plus'
$env:LLM_TIMEOUT_SECONDS='1145'
```

客户端约定：

- 调 `/chat/completions`
- 使用 `response_format={"type":"json_object"}`
- 后端对模型输出再做 JSON 提取和 normalize

---

## 7. 当前建议顺序

### 已进入实现

1. `/ai/analyze-anomaly`
2. `/ai/anomaly-feedback`
3. `/ai/query-assistant`

### 后续

1. `/ai/report-summary`
2. `/ai/qa`
3. `/ai/ops-guide`
