# `/ai/qa` 联调说明

## 1. 目标

这份联调用于验证三件事：

1. 后端 `/ai/qa` 路由是否可访问
2. 后端是否能正确按问题类型执行总览式编排
3. 返回中是否包含：
   - `answer`
   - `question_type`
   - `references.knowledge / data / history_cases`
   - `used_tools`
   - `suggested_actions`
   - `meta`

---

## 2. 需要填写的环境变量

下面这些值请你测试时自己填写：

```powershell
$env:PYTHONPATH='D:\code\服外\fw-backend'
$env:BACKEND_BASE_URL=''
$env:RAGFLOW_API_URL=''
$env:RAGFLOW_API_KEY=''
$env:RAGFLOW_DEFAULT_CHAT_ID=''
$env:RAGFLOW_DATASET_IDS=''
$env:AI_QA_TEST_QUESTION=''
$env:AI_QA_TEST_SESSION_ID=''
$env:AI_QA_DIRECT_RAGFLOW_CHECK='1'
```

说明：

- `BACKEND_BASE_URL`
  - 例如：`http://127.0.0.1:8000`
- `RAGFLOW_API_URL`
  - 例如：`http://127.0.0.1:9380/api/v1`
- `RAGFLOW_API_KEY`
  - RAGFlow 的 API Key
- `RAGFLOW_DEFAULT_CHAT_ID`
  - 当前环境中如果还保留该变量可以继续存在，但新版 `/ai/qa` 第一版主路径不再依赖 RAGFlow chat
- `RAGFLOW_DATASET_IDS`
  - knowledge 检索阶段要检索的知识库 ID，多个值用英文逗号分隔
  - 如果不填，知识型问题大概率拿不到稳定的知识引用
- `AI_QA_TEST_QUESTION`
  - 例如：`冷机报警先查什么？`
- `AI_QA_TEST_SESSION_ID`
  - 可留空；如果要测多轮会话再填写
- `AI_QA_DIRECT_RAGFLOW_CHECK`
  - `1`：先直连 RAGFlow，再调后端
  - `0`：只调后端 `/ai/qa`

---

## 3. 运行脚本

```powershell
& 'C:\Users\Fridayssheep\.conda\envs\fw_env\python.exe' 'D:\code\服外\fw-backend\test\test_ai_qa_integration.py'
```

---

## 4. 输出结果

脚本会同时：

1. 在终端打印 JSON 结果
2. 生成报告文件：

```text
D:\code\服外\fw-backend\test\ai_qa_integration_report.json
```

---

## 5. 结果怎么看

### 成功

至少应满足：

- `backend_http_check.status_code = 200`
- `backend_http_check.answer_preview` 非空
- `backend_http_check.question_type` 非空
- `backend_http_check.provider = orchestrated`
- `backend_http_check.used_tools` 是数组
- `backend_http_check.has_references` 能反映本次是否有证据引用

### 常见失败

- `503`
  - 当前阶段通常不作为 `/ai/qa` 主路径的常见错误
  - 若后续知识检索改成强依赖模式，可能由知识库配置缺失触发

- `502`
  - 当前阶段通常不作为 `/ai/qa` 主路径的常见错误
  - 若知识检索走硬失败模式，可能由上游知识服务异常触发

- `504`
  - 上游模型或知识服务超时

---

## 6. 推荐排查顺序

1. 先看 `direct_ragflow_check`
   - 如果这里失败，优先检查 RAGFlow 地址、API Key、Dataset IDs
2. 再看 `backend_http_check`
   - 如果直连成功但后端失败，说明问题在 `/ai/qa` 编排逻辑或响应适配

---

## 7. 当前脚本覆盖范围

已覆盖：

- RAGFlow retrieval 直连检查
- `/ai/qa` HTTP 联调
- `/ai/qa` 的 question_type / references / used_tools 结果统计

未覆盖：

- 混合问题的多工具编排
- 异常分析上下文完整路径
- 流式输出
