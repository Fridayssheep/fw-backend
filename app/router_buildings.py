from typing import Annotated  # 导入 Annotated，方便给查询参数补充 Query 元数据。

from fastapi import APIRouter  # 导入 APIRouter，方便把 buildings 路由单独拆分管理。
from fastapi import Query  # 导入 Query，方便声明查询参数默认值和文档信息。
from pydantic import BeforeValidator  # 导入前置校验器，方便兼容空字符串分页参数。

from .schemas_buildings import BuildingDetailResponse  # 导入建筑详情响应模型。
from .schemas_buildings import BuildingListResponse  # 导入建筑列表响应模型。
from .schemas_common import ErrorResponse  # 导入统一错误响应模型。
from .schemas_energy import EnergySummaryResponse  # 导入建筑级能耗摘要响应模型。
from .service_common import coerce_blank_to_default  # 导入空字符串回退默认值函数。
from .services_buildings import get_building_detail as get_building_detail_service  # 导入建筑详情业务函数。
from .services_buildings import get_building_energy_summary as get_building_energy_summary_service  # 导入建筑级能耗摘要业务函数。
from .services_buildings import get_buildings as get_buildings_service  # 导入建筑列表业务函数。


router = APIRouter(tags=["Buildings"])  # 创建 buildings 分组路由对象，并统一设置文档标签。
PageQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(1))]  # 定义兼容空字符串的页码参数类型。
PageSizeQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(20))]  # 定义兼容空字符串的每页条数参数类型。


@router.get("/buildings", response_model=BuildingListResponse, summary="获取建筑列表")  # 注册建筑列表查询接口。
def get_buildings_api(  # 定义建筑列表查询处理函数。
    keyword: Annotated[str | None, Query()] = None,  # 声明 keyword 查询参数。
    site_id: Annotated[str | None, Query()] = None,  # 声明 site_id 查询参数。
    primaryspaceusage: Annotated[str | None, Query()] = None,  # 声明 primaryspaceusage 查询参数。
    page: Annotated[PageQueryInt, Query()] = 1,  # 声明页码参数并给默认值，同时兼容空字符串。
    page_size: Annotated[PageSizeQueryInt, Query()] = 20,  # 声明每页条数参数并给默认值，同时兼容空字符串。
) -> BuildingListResponse:  # 返回建筑列表响应模型。
    return get_buildings_service(keyword, site_id, primaryspaceusage, page, page_size)  # 调用业务层并返回结果。


@router.get("/buildings/{buildingId}", response_model=BuildingDetailResponse, summary="获取建筑详情", responses={404: {"model": ErrorResponse}})  # 注册建筑详情查询接口。
def get_building_detail_api(buildingId: str) -> BuildingDetailResponse:  # 定义建筑详情查询处理函数。
    return get_building_detail_service(buildingId)  # 调用业务层并返回结果。


@router.get("/buildings/{buildingId}/energy/summary", response_model=EnergySummaryResponse, summary="获取建筑级能耗摘要", responses={404: {"model": ErrorResponse}})  # 注册建筑级能耗摘要接口。
def get_building_energy_summary_api(  # 定义建筑级能耗摘要处理函数。
    buildingId: str,  # 接收路径里的建筑编号。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    granularity: Annotated[str | None, Query()] = None,  # 声明 granularity 查询参数。
) -> EnergySummaryResponse:  # 返回建筑级能耗摘要响应模型。
    return get_building_energy_summary_service(buildingId, meter, start_time, end_time, granularity)  # 调用业务层并返回结果。
