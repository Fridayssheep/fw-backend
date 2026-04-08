# fW-Backend

基于 FastAPI 和 PostgreSQL 的建筑能耗管理后台。不仅提供传统能料大盘、趋势监控、COP 对标与红黑榜排行能力，深度集成了大语言模型（LLM），提供开箱即用的 AI 问答、数据大盘智能调阅 (MCP 支持) 和离线异常故障诊断闭环。

## 核心特性
- **基于 MCP的AI Agent**：前端发起自然语言问答时，大模型拥有自主检索能耗数据库的能力。支持流式服务端推送（SSE），实时播报 AI 底层工具状态。
- **故障闭环反馈**：孤立森林离线检测建筑能耗异常（基线偏离、突然断流），支持将用户人工判定作为记忆存入数据库，下次遇到相似故障时大模型会自动调用历史经验应对。
- **RAG 领域知识接入**：与 RAGFlow 原生打通，在处置排障时不仅依靠能耗数据本身，也提供厂商维修手册的内容支撑。

---

## 技术栈  
- 框架：FastAPI + Pydantic
- 数据库：PostgreSQL + SQLAlchemy
- 知识库系统：RAGFlow
- 部署：Docker

---

## 部署


### 1. 准备环境变量
进入 `docker` 目录，将模板生成为实际的配置文件：
```bash
cd docker
cp .env.example .env
```
修改`.env`文件中的数据库和LLM相关配置

### 2. 构建并启动容器
```bash
docker compose up -d --build
```

### 3. 可视化确认
- 后端 Swagger API 测试端点：http://127.0.0.1:8000/docs
- 实时 AI 状态 SSE 推流端点：http://127.0.0.1:8000/ai/status
- 数据库 Web 全可视化管理 (PgAdmin)：http://127.0.0.1:5050

---

## 本地测试与开发

### 1. 构建数据库
```bash
cd docker
docker compose up -d db pgadmin
```

### 2. 初始化环境并安装依赖
在根目录执行：
```bash
uv venv .venv

# 激活环境
# Windows: .\.venv\Scripts\Activate.ps1
# Mac/Linux: source .venv/bin/activate

uv pip install -r requirements.txt
```
或使用conda:
```bash
conda create -n fw-backend python=3.12 && conda activate fw-backend && pip install uv && uv pip install -r requirements.txt
```
### 3. 设置环境变量并运行
复制 `.env.example` 里面的数据库和 LLM 相关配置，设为终端全局变量

之后启动 Uvicorn：
```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 关于异常检测工具（开发中）


在容器内或虚拟环境下运行如下脚本以对所有建筑进行异常数据分析：
```bash
python -m app.jobs.offline_anomaly_detector
```
或者，前端也可以直接调用后门的异步接口进行无阻塞挂载任务触发：`POST /ai/trigger-anomaly-detection`

---
