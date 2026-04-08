import os

# MCP 侧参数白名单与后端连接配置。

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "30"))
MCP_DEFAULT_TIME_START = os.getenv("MCP_DEFAULT_TIME_START", "2017-01-01T00:00:00+00:00")
MCP_DEFAULT_TIME_END = os.getenv("MCP_DEFAULT_TIME_END", "2017-01-07T00:00:00+00:00")

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
ALLOWED_COMPARE_METRICS = {"sum", "avg", "peak", "eui"}
ALLOWED_RANKING_METRICS = {"sum", "avg", "peak", "eui"}
ALLOWED_RANKING_ORDERS = {"asc", "desc"}
ALLOWED_ANOMALY_GRANULARITIES = {"hour", "day"}
