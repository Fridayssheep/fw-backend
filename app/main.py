from datetime import datetime  # 导入日期时间类型，方便声明查询参数。
from typing import Annotated  # 导入 Annotated，方便给参数加 Query 元数据。

from fastapi import FastAPI  # 导入 FastAPI 应用类。
from fastapi import Query  # 导入 Query，方便声明查询参数默认值。
from fastapi import Request  # 导入 Request，方便手动读取重复 query 参数。
from fastapi import status  # 导入状态码常量，方便写响应说明。
from fastapi.responses import JSONResponse  # 导入 JSON 响应类，方便统一返回错误结果。

from .database import fetch_scalar  # 导入单值查询函数，用于做数据库探活。
from .schemas import EnergyAnomalyAnalysisRequest  # 导入异常分析请求模型。
from .schemas import EnergyAnomalyAnalysisResponse  # 导入异常分析响应模型。
from .schemas import EnergyCompareResponse  # 导入能耗对比响应模型。
from .schemas import EnergyQueryResponse  # 导入能耗明细响应模型。
from .schemas import EnergyRankingResponse  # 导入能耗排行响应模型。
from .schemas import EnergyTrendResponse  # 导入能耗趋势响应模型。
from .schemas import ErrorResponse  # 导入统一错误响应模型。
from .schemas import SystemHealth  # 导入健康检查响应模型。
from .schemas import WeatherCorrelationResponse  # 导入天气相关性响应模型。
from .schemas import CopAnalysisResponse  # 导入 COP 响应模型。
from .services import get_energy_anomaly_analysis  # 导入异常分析业务函数。
from .services import get_energy_compare  # 导入能耗对比业务函数。
from .services import get_energy_cop  # 导入 COP 业务函数。
from .services import get_energy_query  # 导入能耗明细业务函数。
from .services import get_energy_rankings  # 导入能耗排行业务函数。
from .services import get_energy_trend  # 导入能耗趋势业务函数。
from .services import get_energy_weather_correlation  # 导入天气相关性业务函数。
from .services import get_taipei_now  # 导入获取台湾标准时间的函数。


app = FastAPI(  # 创建 FastAPI 应用实例。
    title="Building Energy AI & Backend API",  # 设置接口文档标题。
    version="0.1.0-local-impl",  # 设置当前本地实现版本号。
    description="最小可运行版 system + energy 接口实现。",  # 设置接口文档描述信息。
)  # 完成应用对象创建。


def parse_building_ids(request: Request) -> list[str] | None:  # 定义解析 building_ids 查询参数的函数。
    raw_values = request.query_params.getlist("building_ids")  # 先读取所有同名 query 参数。
    if not raw_values:  # 如果一个都没传，
        return None  # 就直接返回空。
    parsed_values: list[str] = []  # 初始化最终建筑编号列表。
    for raw_value in raw_values:  # 遍历每一个原始值。
        parsed_values.extend([item.strip() for item in raw_value.split(",") if item.strip()])  # 同时支持重复参数和逗号分隔两种写法。
    return parsed_values or None  # 如果最终列表为空就返回空，否则返回解析好的列表。


@app.exception_handler(Exception)  # 给整个应用注册一个兜底异常处理器。
def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:  # 定义兜底异常处理函数。
    return JSONResponse(  # 返回统一错误结构。
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,  # 返回 500 状态码。
        content=ErrorResponse(code="internal_error", message=str(exc)).model_dump(mode="json"),  # 把异常文本包装成统一错误结构。
    )  # 完成错误响应返回。


@app.exception_handler(ValueError)  # 给应用注册一个参数校验异常处理器。
def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:  # 定义参数校验异常处理函数。
    return JSONResponse(  # 返回统一错误结构。
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,  # 返回 422 状态码。
        content=ErrorResponse(code="validation_error", message=str(exc)).model_dump(mode="json"),  # 把校验错误包装成统一错误结构。
    )  # 完成错误响应返回。


@app.get("/health", response_model=SystemHealth, tags=["System"], summary="服务健康检查")  # 注册 system 健康检查接口。
def get_system_health() -> SystemHealth:  # 定义健康检查处理函数。
    fetch_scalar("SELECT 1")  # 执行最简单的数据库探活查询，只要能跑通就说明数据库可用。
    return SystemHealth(  # 返回符合文档的健康检查响应。
        status="ok",  # 写入服务状态。
        database="ok",  # 写入数据库状态。
        timestamp=get_taipei_now(),  # 写入当前台湾标准时间。
    )  # 完成健康检查响应创建。


@app.get("/energy/query", response_model=EnergyQueryResponse, tags=["Energy"], summary="执行通用能耗查询")  # 注册能耗明细查询接口。
def query_energy_records(  # 定义能耗明细查询函数。
    request: Request,  # 接收原始请求对象，方便手动解析 building_ids。
    site_id: Annotated[str | None, Query()] = None,  # 声明 site_id 查询参数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    granularity: Annotated[str | None, Query()] = None,  # 声明 granularity 查询参数。
    aggregation: Annotated[str | None, Query()] = None,  # 声明 aggregation 查询参数。
    page: Annotated[int, Query()] = 1,  # 声明页码参数并给默认值。
    page_size: Annotated[int, Query()] = 100,  # 声明每页条数参数并给默认值。
) -> EnergyQueryResponse:  # 返回能耗明细响应模型。
    building_ids = parse_building_ids(request)  # 手动解析 building_ids 参数。
    return get_energy_query(building_ids, site_id, meter, start_time, end_time, granularity, aggregation, page, page_size)  # 调用业务层并返回结果。


@app.get("/energy/trend", response_model=EnergyTrendResponse, tags=["Energy"], summary="获取能耗趋势图数据")  # 注册能耗趋势接口。
def get_energy_trend_api(  # 定义能耗趋势处理函数。
    request: Request,  # 接收原始请求对象。
    site_id: Annotated[str | None, Query()] = None,  # 声明 site_id 查询参数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    granularity: Annotated[str | None, Query()] = None,  # 声明 granularity 查询参数。
) -> EnergyTrendResponse:  # 返回趋势响应模型。
    building_ids = parse_building_ids(request)  # 手动解析 building_ids 参数。
    return get_energy_trend(building_ids, site_id, meter, start_time, end_time, granularity)  # 调用业务层并返回结果。


@app.get("/energy/compare", response_model=EnergyCompareResponse, tags=["Energy"], summary="获取多建筑或多对象能耗对比")  # 注册能耗对比接口。
def compare_energy_api(  # 定义能耗对比处理函数。
    request: Request,  # 接收原始请求对象。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    metric: Annotated[str | None, Query()] = None,  # 声明 metric 查询参数。
) -> EnergyCompareResponse:  # 返回对比响应模型。
    building_ids = parse_building_ids(request)  # 手动解析 building_ids 参数。
    return get_energy_compare(building_ids, meter, start_time, end_time, metric)  # 调用业务层并返回结果。


@app.get("/energy/rankings", response_model=EnergyRankingResponse, tags=["Energy"], summary="获取能耗排行")  # 注册能耗排行接口。
def get_energy_rankings_api(  # 定义能耗排行处理函数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    metric: Annotated[str | None, Query()] = None,  # 声明 metric 查询参数。
    order: Annotated[str | None, Query()] = None,  # 声明 order 查询参数。
    limit: Annotated[int, Query()] = 10,  # 声明 limit 查询参数并给默认值。
) -> EnergyRankingResponse:  # 返回排行响应模型。
    return get_energy_rankings(meter, start_time, end_time, metric, order, limit)  # 调用业务层并返回结果。


@app.get("/energy/cop", response_model=CopAnalysisResponse, tags=["Energy"], summary="获取 COP 计算结果")  # 注册 COP 查询接口。
def get_cop_analysis_api(  # 定义 COP 处理函数。
    building_id: Annotated[str | None, Query()] = None,  # 声明 building_id 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    granularity: Annotated[str | None, Query()] = None,  # 声明 granularity 查询参数。
) -> CopAnalysisResponse:  # 返回 COP 响应模型。
    return get_energy_cop(building_id, start_time, end_time, granularity)  # 调用业务层并返回结果。


@app.get("/energy/weather-correlation", response_model=WeatherCorrelationResponse, tags=["Energy"], summary="获取能耗与天气相关性分析")  # 注册天气相关性接口。
def get_weather_correlation_api(  # 定义天气相关性处理函数。
    building_id: Annotated[str | None, Query()] = None,  # 声明 building_id 查询参数。
    meter: Annotated[str | None, Query()] = None,  # 声明 meter 查询参数。
    start_time: Annotated[str | None, Query()] = None,  # 声明 start_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
    end_time: Annotated[str | None, Query()] = None,  # 声明 end_time 查询参数，先按字符串接收，方便兼容未转义的 +08:00。
) -> WeatherCorrelationResponse:  # 返回天气相关性响应模型。
    return get_energy_weather_correlation(building_id, meter, start_time, end_time)  # 调用业务层并返回结果。


@app.post("/energy/anomaly-analysis", response_model=EnergyAnomalyAnalysisResponse, tags=["Energy"], summary="建筑能耗异常分析")  # 注册能耗异常分析接口。
def analyze_energy_anomaly_api(payload: EnergyAnomalyAnalysisRequest) -> EnergyAnomalyAnalysisResponse:  # 定义异常分析处理函数。
    return get_energy_anomaly_analysis(payload)  # 直接调用业务层并返回结果。
