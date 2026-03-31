from typing import Annotated  # 导入 Annotated，方便给查询参数补充 Query 元数据。

from fastapi import APIRouter  # 导入 APIRouter，方便把 devices 路由单独拆分管理。
from fastapi import Query  # 导入 Query，方便声明查询参数默认值和文档信息。

from .schemas import DeviceAlarmListResponse  # 导入设备告警列表响应模型。
from .schemas import DeviceDetailResponse  # 导入设备详情响应模型。
from .schemas import DeviceListResponse  # 导入设备列表响应模型。
from .schemas import ErrorResponse  # 导入统一错误响应模型。
from .schemas import MaintenanceRecordListResponse  # 导入维护记录列表响应模型。
from .services_devices import get_device_alarms as get_device_alarms_service  # 导入设备告警列表业务函数。
from .services_devices import get_device_detail as get_device_detail_service  # 导入设备详情业务函数。
from .services_devices import get_device_maintenance_records as get_device_maintenance_records_service  # 导入设备维护记录业务函数。
from .services_devices import get_devices as get_devices_service  # 导入设备列表业务函数。


router = APIRouter(tags=["Devices"])  # 创建设备分组路由对象，并统一设置文档标签。


@router.get("/devices", response_model=DeviceListResponse, summary="获取设备列表")  # 注册设备列表查询接口。
def get_devices_api(  # 定义设备列表查询处理函数。
    building_id: Annotated[str | None, Query()] = None,  # 声明 building_id 查询参数。
    device_type: Annotated[str | None, Query()] = None,  # 声明 device_type 查询参数。
    status: Annotated[str | None, Query()] = None,  # 声明 status 查询参数。
    page: Annotated[int, Query()] = 1,  # 声明页码参数并给默认值。
    page_size: Annotated[int, Query()] = 20,  # 声明每页条数参数并给默认值。
) -> DeviceListResponse:  # 返回设备列表响应模型。
    return get_devices_service(building_id, device_type, status, page, page_size)  # 调用业务层并返回结果。


@router.get("/devices/{deviceId}", response_model=DeviceDetailResponse, summary="获取设备详情", responses={404: {"model": ErrorResponse}})  # 注册设备详情查询接口。
def get_device_detail_api(deviceId: str) -> DeviceDetailResponse:  # 定义设备详情查询处理函数。
    return get_device_detail_service(deviceId)  # 调用业务层并返回结果。


@router.get("/devices/{deviceId}/alarms", response_model=DeviceAlarmListResponse, summary="获取设备告警记录", responses={404: {"model": ErrorResponse}})  # 注册设备告警列表接口。
def get_device_alarms_api(  # 定义设备告警列表处理函数。
    deviceId: str,  # 接收路径里的设备编号。
    page: Annotated[int, Query()] = 1,  # 声明页码参数并给默认值。
    page_size: Annotated[int, Query()] = 20,  # 声明每页条数参数并给默认值。
) -> DeviceAlarmListResponse:  # 返回设备告警列表响应模型。
    return get_device_alarms_service(deviceId, page, page_size)  # 调用业务层并返回结果。


@router.get("/devices/{deviceId}/maintenance-records", response_model=MaintenanceRecordListResponse, summary="获取设备维护记录", responses={404: {"model": ErrorResponse}})  # 注册设备维护记录列表接口。
def get_device_maintenance_records_api(  # 定义设备维护记录列表处理函数。
    deviceId: str,  # 接收路径里的设备编号。
    page: Annotated[int, Query()] = 1,  # 声明页码参数并给默认值。
    page_size: Annotated[int, Query()] = 20,  # 声明每页条数参数并给默认值。
) -> MaintenanceRecordListResponse:  # 返回维护记录列表响应模型。
    return get_device_maintenance_records_service(deviceId, page, page_size)  # 调用业务层并返回结果。
