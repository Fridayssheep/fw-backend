from .database import fetch_scalar  # 导入单值查询函数，用于做数据库探活。
from .schemas_system import SystemHealth  # 导入健康检查响应模型。
from .service_common import get_taipei_now  # 导入获取台湾标准时间的函数。


def get_system_health() -> SystemHealth:  # 定义健康检查业务函数。
    fetch_scalar("SELECT 1")  # 执行最简单的数据库探活查询，只要能跑通就说明数据库可用。
    return SystemHealth(  # 返回符合文档的健康检查响应。
        status="ok",  # 写入服务状态。
        database="ok",  # 写入数据库状态。
        timestamp=get_taipei_now(),  # 写入当前台湾标准时间。
    )  # 完成健康检查响应创建。
