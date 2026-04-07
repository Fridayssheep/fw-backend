from fastapi import APIRouter, BackgroundTasks  # 导入 APIRouter 和后台任务

from app.schemas.schemas_system import SystemHealth  # 导入健康检查响应模型。
from app.services.services_system import get_system_health as get_system_health_service  # 导入 system 领域的健康检查业务函数。
from app.jobs.offline_anomaly_detector import run_batch_pipeline


router = APIRouter(tags=["System"])  # 创建 system 分组路由对象，并统一设置文档标签。


@router.get("/health", response_model=SystemHealth, summary="服务健康检查")  # 注册 system 健康检查接口。
def get_system_health_api() -> SystemHealth:  # 定义健康检查接口处理函数。
    return get_system_health_service()  # 调用 system 业务层并返回结果。


@router.post("/trigger-anomaly-detection", summary="触发后台离线异常跑批任务")
def trigger_anomaly_detection_api(background_tasks: BackgroundTasks) -> dict[str, str]:
    """触发后台并行离线异常跑批诊断任务，该接口立即返回，由 FastAPI 背景任务在后台执行。"""
    background_tasks.add_task(run_batch_pipeline)
    return {"status": "ok", "message": "异常检测任务已放入队列并在后台并发执行，稍后系统会自动刷新或挂载新的异常告警。"}
