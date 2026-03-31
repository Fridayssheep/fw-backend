# AI历史反馈检索接入设计

## 1. 目标

在下一版 `POST /ai/analyze-anomaly` 中，引入历史反馈检索能力，让 AI 在输出候选原因时，不只依赖：

- 当前异常分析结果
- 知识库
- 规则库

还可以参考：

- 用户过去对相似异常的确认结果
- 历史高分原因
- 历史备注中的处理经验

核心目标有两个：

1. 让 AI 的候选原因排序更贴近真实运维经验
2. 让系统逐步形成项目自己的经验库

---

## 2. 整体流程

```text
异常分析请求
  -> 调用 energy_anomaly_analysis
  -> 得到结构化异常结果
  -> 检索历史反馈表 ai_anomaly_feedback
  -> 选出相似历史案例
  -> 组织成 history_context
  -> 拼进 AI 提示词
  -> 生成候选原因 + 证据 + 建议
  -> 返回给前端
```

---

## 3. 最小实现原则

这一阶段不要做复杂学习系统，只做“检索增强”。

也就是说：

- 不训练模型
- 不在线更新参数
- 不做自动权重学习

只做：

1. 查历史反馈
2. 取相似案例
3. 作为附加上下文喂给模型

这样成本最低，也最符合当前项目阶段。

---

## 4. 检索输入

当 `POST /ai/analyze-anomaly` 被调用时，历史反馈检索至少应拿到这些输入：

| 输入 | 来源 |
|---|---|
| `building_id` | 当前分析请求 |
| `meter` | 当前分析请求 |
| `time_range` | 当前分析请求 |
| `baseline_mode` | 当前异常分析参数 |
| `candidate_causes` | 当前分析阶段已生成的候选原因 |
| `anomaly_summary` | 当前异常分析摘要 |

---

## 5. 检索策略

建议按“强约束 + 弱约束”两层做。

### 5.1 强约束

优先过滤：

- 相同 `meter`
- `resolution_status` 属于有效反馈：
  - `confirmed`
  - `partially_confirmed`
  - `resolved`

这一步是为了先排掉明显无效样本。

### 5.2 弱约束

在强约束结果里再做排序，排序依据建议如下：

1. 同 `building_id` 优先
2. 同 `selected_cause_id` 优先
3. 时间窗口特征接近优先
4. 评分更高优先
5. 更新时间更近优先

---

## 6. 推荐检索优先级

建议分成三层来源，按顺序回退。

### 第一层：同建筑同表计

条件：

- `building_id` 相同
- `meter` 相同

这是最优先的历史经验，因为场景最接近。

### 第二层：同表计跨建筑

条件：

- `meter` 相同
- `building_id` 不同

适用于本建筑历史样本少时，用其他建筑的相似经验补充。

### 第三层：同原因标签经验

如果当前候选原因已经初步生成，可以反向查：

- `selected_cause_id in current_candidate_cause_ids`

这一步用于增强某些原因的“历史支持度”。

---

## 7. 推荐 SQL 检索思路

### 7.1 先查主表

先查 `ai_anomaly_feedback`：

- 同 `meter`
- 只取有效状态
- 优先同 `building_id`
- 按 `selected_score DESC, created_at DESC` 排序

### 7.2 可选再关联子表

如果你们想评估候选排序质量，可以再查：

- `ai_anomaly_feedback_candidate_scores`

用于统计：

- 某个 `cause_id` 平均得分
- 某个 `cause_id` 被高分但未最终选中的次数

但这一步可以后置，不是第一阶段刚需。

---

## 8. 检索结果结构

建议统一整理成 AI 可直接消费的 `history_context`：

```json
{
  "history_context": {
    "matched_case_count": 4,
    "top_confirmed_causes": [
      {
        "cause_id": "cooling_load_rise",
        "count": 3,
        "avg_score": 4.67
      },
      {
        "cause_id": "efficiency_drop",
        "count": 1,
        "avg_score": 4.0
      }
    ],
    "matched_cases": [
      {
        "feedback_id": "feedback_001",
        "building_id": "Bear_assembly_Angel",
        "meter": "electricity",
        "selected_cause_id": "cooling_load_rise",
        "selected_score": 5,
        "resolution_status": "confirmed",
        "comment": "现场确认该时段冷负荷明显升高。",
        "created_at": "2026-03-30T16:00:00+08:00"
      }
    ]
  }
}
```

---

## 9. 如何拼进 AI 提示词

不要把完整历史记录原样灌给模型。应先做摘要压缩。

### 推荐拼法

给模型的历史经验上下文建议只保留：

1. 命中案例数量
2. 高频原因排序
3. 1 到 3 条最有代表性的历史备注

例如：

```text
历史相似反馈参考：
- 共检索到 4 条有效相似案例
- 其中 3 条最终确认原因是 cooling_load_rise，平均评分 4.67
- 另 1 条最终确认原因是 efficiency_drop，平均评分 4.0
- 代表性备注：
  1. 现场确认该时段冷负荷明显升高
  2. 天气升温只能部分解释异常，最终定位为供冷策略问题
```

然后提示模型：

- 优先参考已确认次数更多、评分更高的历史经验
- 但不能机械照抄，必须结合当前证据重新判断

---

## 10. 接入到 AI 输出的方式

历史反馈接入后，建议影响以下三个输出部分：

### 10.1 `candidate_causes` 排序

如果某个原因在历史上被高频确认，可以提高排序，但不能跳过当前证据判断。

### 10.2 `evidence`

新增一种证据类型：

- `history_case`

例如：

```json
{
  "evidence_id": "hist_001",
  "type": "history_case",
  "source": "ai_anomaly_feedback",
  "snippet": "历史上 3 条相似案例最终确认原因均为 cooling_load_rise",
  "weight": 0.72
}
```

### 10.3 `answer`

回答中可以加入一句：

- “历史上存在 3 条相似案例，最终均确认与冷负荷异常升高有关。”

---

## 11. 风险控制

### 11.1 历史经验不能覆盖当前证据

历史反馈只能做增强，不能直接决定结论。

否则会导致：

- 模型盲目重复旧结论
- 新型故障被老经验误导

### 11.2 低质量反馈要降权

以下情况建议降权或过滤：

- `selected_score <= 2`
- `resolution_status = rejected`
- `comment` 明显为空且信息不足

### 11.3 样本过少时不要过度引用

如果只命中 1 条历史案例，建议仅轻量提示：

- “存在 1 条相似历史记录，可作为弱参考”

不要把它说成稳定规律。

---

## 12. 第一阶段最小实现

### 必做

1. 查 `ai_anomaly_feedback`
2. 按 `building_id + meter` 优先匹配
3. 取前 `3-5` 条有效案例
4. 压缩成 `history_context`
5. 拼进 AI 提示词

### 暂缓

1. 不做复杂相似度算法
2. 不做 embedding 检索
3. 不做自动学习
4. 不做候选原因权重训练

---

## 13. 推荐后续接口内部流程

`POST /ai/analyze-anomaly` 内部建议变成：

```text
1. 调 energy_anomaly_analysis
2. 基于结构化结果生成初步候选原因
3. 查询 ai_anomaly_feedback 历史反馈
4. 组织 history_context
5. 把当前异常 + 知识库 + history_context 一起交给模型
6. 返回最终 candidate_causes / evidence / answer
```

---

## 14. 下一步

第四步设计完成后，下一步可以继续做：

1. 为后端定义历史反馈检索查询接口或内部 service 输入输出
2. 为 AI 提示词设计“当前异常 + 历史反馈”的拼接模板

