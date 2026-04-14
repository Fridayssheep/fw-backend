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


### 1. 准备环境变量与 AI 配置
进入 `docker` 目录，将模板生成为实际的配置文件：
```bash
cd docker
cp .env.example .env
cp ai_settings_example.json ai_settings.json
```
修改 `.env` 文件以配置数据库连接，并修改 `ai_settings.json` 来配置 LLM 和 RAGFlow 的相关节点、模型与密钥。

### 2. 构建并启动容器
在 `docker` 目录下执行：
```bash
docker compose up -d --build
```

### 3. 可视化确认
- 后端 Swagger API 测试端点：http://127.0.0.1:8000/docs
- 实时 AI 状态 SSE 推流端点：http://127.0.0.1:8000/ai/status
- 数据库 Web 全可视化管理 (PgAdmin)：http://127.0.0.1:5050

---

## 本地测试与开发

### 1. 运行数据库服务
为了方便本地调试主程序，我们仍然使用 Docker 运行 PostgreSQL 和 PgAdmin：
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
### 3. 设置配置文件并运行
请将 `.env.example` 中的数据库配置设定为终端的全局变量（或者使用工具加载 `.env`）。

同时，初始化运行时的 AI 配置文件：
```bash
# 回到项目根目录
mkdir -p data/runtime
cp docker/ai_settings_example.json data/runtime/ai_settings.json
```
根据你的实际环境情况修改 `data/runtime/ai_settings.json` 中的各 AI 密钥和服务地址。

之后启动 Uvicorn：
```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
