from typing import Annotated  # 导入 Annotated，方便给查询参数补充 Query 元数据。

from fastapi import APIRouter  # 导入 APIRouter，方便把 energy 路由单独拆分管理。
from fastapi import Query  # 导入 Query，方便声明查询参数默认值和文档信息。
from fastapi import Request  # 导入 Request，方便手动读取重复 query 参数。
from pydantic import BeforeValidator  # 导入前置校验器，方便兼容空字符串数字参数。

from app.services.service_common import coerce_blank_to_default  # 导入空字符串回退默认值函数。
from app.schemas.schemas_energy import CopAnalysisResponse  # 导入 COP 响应模型。
from app.schemas.schemas_energy import EnergyAnomalyAnalysisRequest  # 导入异常分析请求模型。
from app.schemas.schemas_energy import EnergyAnomalyAnalysisResponse  # 导入异常分析响应模型。
from app.schemas.schemas_energy import EnergyCompareResponse  # 导入能耗对比响应模型。
from app.schemas.schemas_energy import EnergyQueryResponse  # 导入能耗明细响应模型。
from app.schemas.schemas_energy import EnergyRankingResponse  # 导入能耗排行响应模型。
from app.schemas.schemas_energy import EnergyTrendResponse  # 导入能耗趋势响应模型。
from app.schemas.schemas_energy import WeatherCorrelationResponse  # 导入天气相关性响应模型。
from app.services.services_anomaly import get_energy_anomaly_analysis as get_energy_anomaly_analysis_service  # 导入异常分析业务函数。
from app.services.services_energy import get_energy_compare as get_energy_compare_service  # 导入能耗对比业务函数。
from app.services.services_energy import get_energy_cop as get_energy_cop_service  # 导入 COP 业务函数。
from app.services.services_energy import get_energy_query as get_energy_query_service  # 导入能耗明细业务函数。
from app.services.services_energy import get_energy_rankings as get_energy_rankings_service  # 导入能耗排行业务函数。
from app.services.services_energy import get_energy_trend as get_energy_trend_service  # 导入能耗趋势业务函数。
from app.services.services_energy import get_energy_weather_correlation as get_energy_weather_correlation_service  # 导入天气相关性业务函数。


router = APIRouter(tags=["Energy"])  # 创建 energy 分组路由对象，并统一设置文档标签。
PageQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(1))]  # 定义兼容空字符串的页码参数类型。
PageSizeQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(20))]  # 定义兼容空字符串的每页条数参数类型。
LimitQueryInt = Annotated[int, BeforeValidator(coerce_blank_to_default(10))]  # 定义兼容空字符串的 limit 参数类型。


def parse_building_ids(request: Request) -> list[str] | None:  # 定义解析 building_ids 查询参数的函数。
    raw_values = request.query_params.getlist("building_ids")  # 先读取所有同名 query 参数。
    if not raw_values:  # 如果一个都没传，
        return None  # 就直接返回空。
    parsed_values: list[str] = []  # 初始化最终建筑编号列表。
    for raw_value in raw_values:  # 遍历每一个原始值。
        parsed_values.extend([item.strip() for item in raw_value.split(",") if item.strip()])  # 同时支持重复参数和逗号分隔两种写法。
    return parsed_values or None  # 如果最终列表为空就返回空，否则返回解析好的列表。


@router.get("/energy/query", response_model=EnergyQueryResponse, summary="执行通用能耗查询")  # 注册能耗明细查询接口。
def query_energy_records(  # 定义能耗明细查询函数。
    request: Request,  # 接收原始请求对象，方便手动解析 building_ids。
    site_id: Annotated[str | None, Query()] = None,  # 声明 site_id 查询参数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    granularity: Annotated[str | None, Query()] = None,  # 声明 granularity 查询参数。
    aggregation: Annotated[str | None, Query()] = None,  # 声明 aggregation 查询参数。
    page: Annotated[PageQueryInt, Query()] = 1,  # 声明页码参数并给默认值，同时兼容空字符串。
    page_size: Annotated[PageSizeQueryInt, Query()] = 20,  # 声明每页条数参数并给默认值，同时兼容空字符串。
) -> EnergyQueryResponse:  # 返回能耗明细响应模型。
    building_ids = parse_building_ids(request)  # 手动解析 building_ids 参数。
    return get_energy_query_service(building_ids, site_id, meter, start_time, end_time, granularity, aggregation, page, page_size)  # 调用业务层并返回结果。


@router.get("/energy/trend", response_model=EnergyTrendResponse, summary="获取能耗趋势图数据")  # 注册能耗趋势接口。
def get_energy_trend_api(  # 定义能耗趋势处理函数。
    request: Request,  # 接收原始请求对象。
    site_id: Annotated[str | None, Query()] = None,  # 声明 site_id 查询参数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    granularity: Annotated[str | None, Query()] = None,  # 声明 granularity 查询参数。
) -> EnergyTrendResponse:  # 返回趋势响应模型。
    building_ids = parse_building_ids(request)  # 手动解析 building_ids 参数。
    return get_energy_trend_service(building_ids, site_id, meter, start_time, end_time, granularity)  # 调用业务层并返回结果。


@router.get("/energy/compare", response_model=EnergyCompareResponse, summary="获取多建筑或多对象能耗对比")  # 注册能耗对比接口。
def compare_energy_api(  # 定义能耗对比处理函数。
    request: Request,  # 接收原始请求对象。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    metric: Annotated[str | None, Query()] = None,  # 声明 metric 查询参数。
) -> EnergyCompareResponse:  # 返回对比响应模型。
    building_ids = parse_building_ids(request)  # 手动解析 building_ids 参数。
    return get_energy_compare_service(building_ids, meter, start_time, end_time, metric)  # 调用业务层并返回结果。


@router.get("/energy/rankings", response_model=EnergyRankingResponse, summary="获取能耗排行")  # 注册能耗排行接口。
def get_energy_rankings_api(  # 定义能耗排行处理函数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    metric: Annotated[str | None, Query()] = None,  # 声明 metric 查询参数。
    order: Annotated[str | None, Query()] = None,  # 声明 order 查询参数。
    limit: Annotated[LimitQueryInt, Query()] = 10,  # 声明 limit 查询参数并给默认值，同时兼容空字符串。
) -> EnergyRankingResponse:  # 返回排行响应模型。
    return get_energy_rankings_service(meter, start_time, end_time, metric, order, limit)  # 调用业务层并返回结果。


@router.get("/energy/cop", response_model=CopAnalysisResponse, summary="获取 COP 计算结果")  # 注册 COP 查询接口。
def get_cop_analysis_api(  # 定义 COP 处理函数。
    building_id: Annotated[str | None, Query()] = None,  # 声明 building_id 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    granularity: Annotated[str | None, Query()] = None,  # 声明 granularity 查询参数。
) -> CopAnalysisResponse:  # 返回 COP 响应模型。
    return get_energy_cop_service(building_id, start_time, end_time, granularity)  # 调用业务层并返回结果。


@router.get("/energy/weather-correlation", response_model=WeatherCorrelationResponse, summary="获取能耗与天气相关性分析")  # 注册天气相关性接口。
def get_weather_correlation_api(  # 定义天气相关性处理函数。
    building_id: Annotated[str | None, Query()] = None,  # 声明 building_id 查询参数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
) -> WeatherCorrelationResponse:  # 返回天气相关性响应模型。
    return get_energy_weather_correlation_service(building_id, meter, start_time, end_time)  # 调用业务层并返回结果。


@router.post("/energy/anomaly-analysis", response_model=EnergyAnomalyAnalysisResponse, summary="建筑能耗异常分析")  # 注册能耗异常分析接口。
def analyze_energy_anomaly_api(payload: EnergyAnomalyAnalysisRequest) -> EnergyAnomalyAnalysisResponse:  # 定义异常分析处理函数。
    return get_energy_anomaly_analysis_service(payload)  # 直接调用业务层并返回结果。
