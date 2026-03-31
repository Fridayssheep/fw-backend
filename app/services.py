# 此文件保留为兼容导出层，方便旧的导入路径继续可用。
# 当前文件不再放业务实现，只负责汇总各领域服务函数。

from .service_common import ResourceNotFoundError  # 导出资源不存在异常，兼容旧引用。
from .service_common import get_taipei_now  # 导出获取台湾时间的函数，兼容旧引用。
from .services_buildings import get_building_detail  # 导出建筑详情业务函数，兼容旧引用。
from .services_buildings import get_building_energy_summary  # 导出建筑级能耗摘要业务函数，兼容旧引用。
from .services_buildings import get_buildings  # 导出建筑列表业务函数，兼容旧引用。
from .services_devices import get_device_alarms  # 导出设备告警列表业务函数，兼容旧引用。
from .services_devices import get_device_detail  # 导出设备详情业务函数，兼容旧引用。
from .services_devices import get_device_maintenance_records  # 导出设备维护记录业务函数，兼容旧引用。
from .services_devices import get_devices  # 导出设备列表业务函数，兼容旧引用。
from .services_energy import build_summary  # 导出能耗摘要构造函数，兼容旧引用。
from .services_energy import get_energy_anomaly_analysis  # 导出异常分析业务函数，兼容旧引用。
from .services_energy import get_energy_compare  # 导出能耗对比业务函数，兼容旧引用。
from .services_energy import get_energy_cop  # 导出 COP 业务函数，兼容旧引用。
from .services_energy import get_energy_query  # 导出能耗明细业务函数，兼容旧引用。
from .services_energy import get_energy_rankings  # 导出能耗排行业务函数，兼容旧引用。
from .services_energy import get_energy_trend  # 导出能耗趋势业务函数，兼容旧引用。
from .services_energy import get_energy_weather_correlation  # 导出天气相关性业务函数，兼容旧引用。
from .services_system import get_system_health  # 导出健康检查业务函数，兼容旧引用。


__all__ = [  # 定义兼容导出列表。
    "ResourceNotFoundError",  # 导出资源不存在异常。
    "build_summary",  # 导出能耗摘要构造函数。
    "get_building_detail",  # 导出建筑详情业务函数。
    "get_building_energy_summary",  # 导出建筑级能耗摘要业务函数。
    "get_buildings",  # 导出建筑列表业务函数。
    "get_device_alarms",  # 导出设备告警列表业务函数。
    "get_device_detail",  # 导出设备详情业务函数。
    "get_device_maintenance_records",  # 导出设备维护记录业务函数。
    "get_devices",  # 导出设备列表业务函数。
    "get_energy_anomaly_analysis",  # 导出异常分析业务函数。
    "get_energy_compare",  # 导出能耗对比业务函数。
    "get_energy_cop",  # 导出 COP 业务函数。
    "get_energy_query",  # 导出能耗明细业务函数。
    "get_energy_rankings",  # 导出能耗排行业务函数。
    "get_energy_trend",  # 导出能耗趋势业务函数。
    "get_energy_weather_correlation",  # 导出天气相关性业务函数。
    "get_system_health",  # 导出健康检查业务函数。
    "get_taipei_now",  # 导出获取台湾时间的函数。
]  # 结束兼容导出列表定义。
