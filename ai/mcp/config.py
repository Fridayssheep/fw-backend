import os

# MCP 侧参数白名单与后端连接配置。

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "30"))

ALLOWED_METERS = {
    "electricity",
    "water",
    "gas",
    "steam",
    "chilledwater",
    "hotwater",
    "irrigation",
    "solar",
}
ALLOWED_GRANULARITIES = {"hour", "day", "week", "month"}
ALLOWED_QUERY_AGGREGATIONS = {"sum", "avg", "max", "min"}
ALLOWED_COMPARE_METRICS = {"sum", "avg", "peak"}
ALLOWED_RANKING_METRICS = {"sum", "avg", "peak"}
ALLOWED_RANKING_ORDERS = {"asc", "desc"}
ALLOWED_BASELINE_MODES = {"overall_mean", "same_hour_mean"}
ALLOWED_ANOMALY_GRANULARITIES = {"hour", "day"}