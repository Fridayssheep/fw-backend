from typing import Annotated  # 导入 Annotated，方便给查询参数补充 Query 元数据。

from fastapi import APIRouter  # 导入 APIRouter，方便把 meters 路由单独拆分管理。
from fastapi import Path  # 导入 Path，方便给路径参数补充文档和校验。
from fastapi import Query  # 导入 Query，方便声明查询参数默认值和文档信息。
from pydantic import BeforeValidator  # 导入前置校验器，方便兼容空字符串分页参数。

from .schemas import ErrorResponse  # 导入统一错误响应模型。
from .schemas import MaintenanceRecordListResponse  # 导入维护记录列表响应模型。
from .schemas import MeterAlarmListResponse  # 导入表计告警列表响应模型。
from .schemas import MeterDetailResponse  # 导入表计详情响应模型。
from .schemas import MeterListResponse  # 导入表计列表响应模型。
from .schemas import MeterStatus  # 导入表计状态枚举。
from .service_common import coerce_blank_to_default  # 导入空字符串回退默认值函数。
from .services_meters import get_meter_alarms as get_meter_alarms_service  # 导入表计告警列表业务函数。
from .services_meters import get_meter_detail as get_meter_detail_service  # 导入表计详情业务函数。
from .services_meters import get_meter_maintenance_records as get_meter_maintenance_records_service  # 导入表计维护记录业务函数。
from .services_meters import get_meters as get_meters_service  # 导入表计列表业务函数。


router = APIRouter(tags=["Meters"])  # 创建表计分组路由对象，并统一设置文档标签。
PageQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(1))]  # 定义兼容空字符串的页码参数类型。
PageSizeQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(20))]  # 定义兼容空字符串的每页条数参数类型。


@router.get("/meters", response_model=MeterListResponse, summary="获取表计列表", operation_id="listMeters")  # 注册表计列表查询接口。
def get_meters_api(  # 定义表计列表查询处理函数。
    building_id: Annotated[str | None, Query(description="建筑 ID")] = None,  # 声明 building_id 查询参数。
    meter_type: Annotated[str | None, Query(description="表计类型")] = None,  # 声明 meter_type 查询参数。
    status: Annotated[MeterStatus | None, Query(description="表计状态")] = None,  # 声明表计状态查询参数。
    page: Annotated[PageQueryInt, Query(ge=1, description="页码")] = 1,  # 声明页码参数并限制最小值，同时兼容空字符串。
    page_size: Annotated[PageSizeQueryInt, Query(ge=1, le=100, description="每页条数")] = 20,  # 声明每页条数参数并限制范围，同时兼容空字符串。
) -> MeterListResponse:  # 返回表计列表响应模型。
    normalized_status = status.value if status is not None else None  # 把状态枚举转换成业务层使用的字符串。
    return get_meters_service(building_id, meter_type, normalized_status, page, page_size)  # 调用业务层并返回结果。


@router.get("/meters/{meterId}", response_model=MeterDetailResponse, summary="获取表计详情", operation_id="getMeterById", responses={404: {"model": ErrorResponse}})  # 注册表计详情查询接口。
def get_meter_detail_api(  # 定义表计详情查询处理函数。
    meterId: Annotated[str, Path(description="表计 ID")],  # 接收路径里的表计编号。
) -> MeterDetailResponse:  # 返回表计详情响应模型。
    return get_meter_detail_service(meterId)  # 调用业务层并返回结果。


@router.get("/meters/{meterId}/alarms", response_model=MeterAlarmListResponse, summary="获取表计告警记录", operation_id="getMeterAlarms", responses={404: {"model": ErrorResponse}})  # 注册表计告警列表接口。
def get_meter_alarms_api(  # 定义表计告警列表处理函数。
    meterId: Annotated[str, Path(description="表计 ID")],  # 接收路径里的表计编号。
    page: Annotated[PageQueryInt, Query(ge=1, description="页码")] = 1,  # 声明页码参数并限制最小值，同时兼容空字符串。
    page_size: Annotated[PageSizeQueryInt, Query(ge=1, le=100, description="每页条数")] = 20,  # 声明每页条数参数并限制范围，同时兼容空字符串。
) -> MeterAlarmListResponse:  # 返回表计告警列表响应模型。
    return get_meter_alarms_service(meterId, page, page_size)  # 调用业务层并返回结果。


@router.get("/meters/{meterId}/maintenance-records", response_model=MaintenanceRecordListResponse, summary="获取表计维护记录", operation_id="getMeterMaintenanceRecords", responses={404: {"model": ErrorResponse}})  # 注册表计维护记录列表接口。
def get_meter_maintenance_records_api(  # 定义表计维护记录列表处理函数。
    meterId: Annotated[str, Path(description="表计 ID")],  # 接收路径里的表计编号。
    page: Annotated[PageQueryInt, Query(ge=1, description="页码")] = 1,  # 声明页码参数并限制最小值，同时兼容空字符串。
    page_size: Annotated[PageSizeQueryInt, Query(ge=1, le=100, description="每页条数")] = 20,  # 声明每页条数参数并限制范围，同时兼容空字符串。
) -> MaintenanceRecordListResponse:  # 返回维护记录列表响应模型。
    return get_meter_maintenance_records_service(meterId, page, page_size)  # 调用业务层并返回结果。
