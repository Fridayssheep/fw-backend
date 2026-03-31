# fw-backend

建筑能耗比赛演示版后端，当前已经实现：

- `GET /health`
- `GET /buildings`
- `GET /buildings/{buildingId}`
- `GET /buildings/{buildingId}/energy/summary`
- `GET /devices`
- `GET /devices/{deviceId}`
- `GET /devices/{deviceId}/alarms`
- `GET /devices/{deviceId}/maintenance-records`
- `GET /energy/query`
- `GET /energy/trend`
- `GET /energy/compare`
- `GET /energy/rankings`
- `GET /energy/cop`
- `GET /energy/weather-correlation`
- `POST /energy/anomaly-analysis`

## 快速启动

### 1. 启动数据库

```powershell
cd \fw-backend\docker
docker compose up -d
```

### 2. 安装依赖

```powershell
cd \fw-backend
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
```

### 3. 配置数据库环境变量

如果数据库跑在你当前 Docker 容器映射端口：

```powershell
$env:DB_HOST = "127.0.0.1"
$env:DB_PORT = "5432"
$env:DB_NAME = "building_energy"
$env:DB_USER = "admin"
$env:DB_PASSWORD = "adminpassword"
```

### 4. 启动后端

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

启动后访问：

- Swagger: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## 当前技术栈

- FastAPI
- SQLAlchemy
- PostgreSQL
- Docker
- uv
