# AI异常反馈表设计

## 1. 目标

该表用于记录用户对一次 AI 异常分析结果的确认、评分和备注，并为后续“历史相似案例检索”提供结构化经验样本。

该表不负责保存完整异常原始时序数据，只保存：

- 本次分析的标识信息
- 用户最终选择的原因
- 候选原因评分
- 处理结果和备注

---

## 2. 主表：`ai_anomaly_feedback`

### 2.1 作用

一条记录代表用户对一次 `analysis_id` 的反馈确认结果。

### 2.2 字段

| 字段 | 类型 | 是否必填 | 说明 |
|---|---|---|---|
| `feedback_id` | uuid | 是 | 主键 |
| `analysis_id` | varchar(64) | 是 | 对应 `/ai/analyze-anomaly` 返回的分析 ID |
| `building_id` | varchar(128) | 是 | 建筑 ID |
| `meter` | varchar(64) | 是 | 表计类型 |
| `time_start` | timestamptz | 是 | 本次分析时间范围开始 |
| `time_end` | timestamptz | 是 | 本次分析时间范围结束 |
| `selected_cause_id` | varchar(128) | 是 | 用户最终确认的候选原因 ID |
| `selected_score` | smallint | 是 | 用户对最终原因的评分，建议 1-5 |
| `resolution_status` | varchar(32) | 是 | `confirmed` / `partially_confirmed` / `rejected` / `resolved` |
| `comment` | text | 否 | 用户备注 |
| `operator_id` | varchar(128) | 否 | 提交人 ID |
| `operator_name` | varchar(128) | 否 | 提交人名称 |
| `model_name` | varchar(128) | 否 | 生成该分析时使用的模型名 |
| `baseline_mode` | varchar(64) | 否 | 异常分析基线模式 |
| `created_at` | timestamptz | 是 | 创建时间 |
| `updated_at` | timestamptz | 是 | 更新时间 |

### 2.3 约束建议

- `analysis_id` 建唯一索引  
  理由：默认一条分析只收一条最终反馈。如果你们以后允许多次修订，再改成普通索引。

- `selected_score` 限制在 `1-5`

- `time_end >= time_start`

---

## 3. 子表：`ai_anomaly_feedback_candidate_scores`

### 3.1 作用

保存用户对多个候选原因逐项评分的结果。  
如果前端只提交最终选中原因，也可以不写这张表。

### 3.2 字段

| 字段 | 类型 | 是否必填 | 说明 |
|---|---|---|---|
| `id` | bigserial | 是 | 主键 |
| `feedback_id` | uuid | 是 | 关联主表 |
| `cause_id` | varchar(128) | 是 | 候选原因 ID |
| `score` | smallint | 是 | 用户评分，1-5 |
| `created_at` | timestamptz | 是 | 创建时间 |

### 3.3 约束建议

- 唯一约束：`(feedback_id, cause_id)`
- `score` 限制在 `1-5`

---

## 4. 为什么拆主表和子表

### 主表保存“最终确认结果”

后续做统计、做相似案例检索时，最常用的是：

- 本次最终确认是什么原因
- 是哪个建筑、哪个 meter、哪个时间段
- 用户是否确认

这些都应该在主表直接查到。

### 子表保存“候选原因评分”

这个是更细粒度的信息，主要用于：

- 分析 AI 候选排序是否合理
- 判断某些原因是否经常被高分但未被选中
- 后续做 rerank 或经验排序

---

## 5. 推荐查询场景

### 5.1 查相似历史案例

按以下条件筛选：

- 同 `building_id`
- 同 `meter`
- 相近时间范围或季节
- 同 `selected_cause_id`

### 5.2 统计原因命中率

统计：

- 某个 `cause_id` 被最终选中的次数
- 某个 `cause_id` 平均评分

### 5.3 排查模型排序质量

结合子表统计：

- 高置信候选却经常被低分
- 低置信候选却经常被高分

---

## 6. 下一步用途

这两张表设计完成后，下一步就可以做：

1. 后端实现 `POST /ai/anomaly-feedback`
2. AI 分析前增加“历史相似反馈检索”
3. 把命中的历史经验拼进下一轮 AI 推理上下文

