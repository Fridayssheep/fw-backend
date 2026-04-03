from typing import Annotated  # 导入 Annotated，方便给查询参数补充 Query 元数据。

from fastapi import APIRouter  # 导入 APIRouter，方便把 dashboard 路由拆分管理。
from fastapi import Query  # 导入 Query，方便声明 dashboard 查询参数。
from pydantic import BeforeValidator  # 导入前置校验器，方便兼容空字符串 limit 参数。

from .schemas_dashboard import DashboardHighlightsResponse  # 导入 dashboard 高亮列表响应模型。
from .schemas_dashboard import DashboardOverviewResponse  # 导入 dashboard 总览响应模型。
from .service_common import coerce_blank_to_default  # 导入空字符串回退默认值函数。
from .services_dashboard import get_dashboard_highlights as get_dashboard_highlights_service  # 导入 dashboard 高亮业务函数。
from .services_dashboard import get_dashboard_overview as get_dashboard_overview_service  # 导入 dashboard 总览业务函数。


router = APIRouter(tags=["Dashboard"])  # 创建 dashboard 分组路由对象，并统一设置文档标签。
LimitQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(3))]  # 定义兼容空字符串的 limit 参数类型。


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse, summary="获取 dashboard 总览数据")  # 注册 dashboard 总览接口。
def get_dashboard_overview_api(  # 定义 dashboard 总览接口处理函数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收以兼容未转义时区格式。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收以兼容未转义时区格式。
    site_id: Annotated[str | None, Query()] = None,  # 声明 site_id 查询参数。
    building_id: Annotated[str | None, Query()] = None,  # 声明 building_id 查询参数。
) -> DashboardOverviewResponse:  # 返回 dashboard 总览响应模型。
    return get_dashboard_overview_service(start_time, end_time, site_id, building_id)  # 调用业务层并返回 dashboard 总览结果。


@router.get("/dashboard/highlights", response_model=DashboardHighlightsResponse, summary="获取 dashboard 首页高亮数据")  # 注册 dashboard 高亮接口。
def get_dashboard_highlights_api(  # 定义 dashboard 高亮接口处理函数。
    limit: Annotated[LimitQueryInt, Query()] = 3,  # 声明 limit 查询参数并给默认值，同时兼容空字符串。
) -> DashboardHighlightsResponse:  # 返回 dashboard 高亮列表响应模型。
    return get_dashboard_highlights_service(limit)  # 调用业务层并返回 dashboard 高亮结果。
