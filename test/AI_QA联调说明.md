# `/ai/qa` 联调说明

## 1. 目标

这份联调用于验证三件事：

1. 后端 `/ai/qa` 路由是否可访问
2. 后端是否能正确调用 RAGFlow OpenAI-compatible 聊天接口
3. 返回中是否包含：
   - `answer`
   - `session_id`
   - `references.chunks`
   - `references.doc_aggs`
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
  - 用于 `/ai/qa` 的目标 Chat ID
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
- `backend_http_check.reference_chunk_count >= 0`
- `backend_http_check.provider = ragflow`
- `backend_http_check.used_openai_compatible = true`

### 常见失败

- `503`
  - RAGFlow 配置缺失
  - 常见是 `RAGFLOW_API_KEY` 或 `RAGFLOW_DEFAULT_CHAT_ID` 没填

- `502`
  - RAGFlow 鉴权失败
  - Chat ID 不存在
  - RAGFlow 返回结构不符合预期

- `504`
  - RAGFlow 超时

---

## 6. 推荐排查顺序

1. 先看 `direct_ragflow_check`
   - 如果这里就失败，优先检查 RAGFlow 地址、API Key、Chat ID
2. 再看 `backend_http_check`
   - 如果直连成功但后端失败，说明问题在后端路由、service 或响应适配

---

## 7. 当前脚本覆盖范围

已覆盖：

- RAGFlow 直连检查
- `/ai/qa` HTTP 联调
- 返回引用数量统计

未覆盖：

- 多轮会话行为是否真的被上游保留
- 超长回答
- 流式输出
