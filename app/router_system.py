from fastapi import APIRouter  # 导入 APIRouter，方便把 system 路由单独拆分管理。

from .schemas import SystemHealth  # 导入健康检查响应模型。
from .services_system import get_system_health as get_system_health_service  # 导入 system 领域的健康检查业务函数。


router = APIRouter(tags=["System"])  # 创建 system 分组路由对象，并统一设置文档标签。


@router.get("/health", response_model=SystemHealth, summary="服务健康检查")  # 注册 system 健康检查接口。
def get_system_health_api() -> SystemHealth:  # 定义健康检查接口处理函数。
    return get_system_health_service()  # 调用 system 业务层并返回结果。
