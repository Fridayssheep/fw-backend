from typing import Annotated  # 导入 Annotated，用于给查询参数补充描述元数据。

from fastapi import APIRouter
from fastapi import HTTPException  # 导入 APIRouter，用于注册报表路由。
from fastapi import Query  # 导入 Query，用于声明查询参数规则。
from fastapi import Request  # 导入 Request，用于读取当前服务基础 URL。
from fastapi.responses import Response  # 导入 Response，用于直接返回下载附件。

from app.schemas.schemas_common import ErrorResponse
from app.schemas.schemas_reports import DeleteReportResponse  # 导入统一错误响应模型。
from app.schemas.schemas_reports import GenerateReportRequest  # 导入报表生成请求模型。
from app.schemas.schemas_reports import GenerateReportResponse  # 导入报表生成响应模型。
from app.schemas.schemas_reports import ReportDetailResponse
from app.services.service_common import ResourceNotFoundError  # 导入报表详情响应模型。
from app.services.services_reports import delete_report as delete_report_service
from app.services.services_reports import generate_report as generate_report_service  # 导入报表生成服务函数。
from app.services.services_reports import get_report_detail as get_report_detail_service  # 导入报表详情服务函数。
from app.services.services_reports import get_report_export as get_report_export_service  # 导入报表导出服务函数。


router = APIRouter(tags=["Reports"])  # 创建报表路由分组并标注为 Reports。


@router.post("/reports/generate", response_model=GenerateReportResponse, summary="创建报表生成任务", operation_id="generateReport")  # 注册“生成报表”接口。
def generate_report_api(  # 定义“生成报表”接口处理函数。
    payload: GenerateReportRequest,  # 接收报表生成请求体。
    request: Request,  # 接收当前请求对象。
) -> GenerateReportResponse:  # 返回报表生成响应模型。
    base_url = str(request.base_url).rstrip("/")  # 读取并规范化基础 URL（去掉末尾斜杠）。
    return generate_report_service(payload, base_url)  # 调用服务层完成报表生成并返回结果。


@router.get("/reports/{reportId}", response_model=ReportDetailResponse, summary="获取报表详情", operation_id="getReportById", responses={404: {"model": ErrorResponse}})  # 注册“查询报表详情/下载导出”接口。
def get_report_detail_api(  # 定义“查询报表详情/下载导出”接口处理函数。
    reportId: str,  # 接收路径参数 reportId。
    request: Request,  # 接收当前请求对象。
    download: Annotated[bool, Query(description="是否直接下载导出文件")] = False,  # 声明是否走下载分支。
    format: Annotated[str, Query(description="导出格式，仅支持 md")] = "md",  # 声明导出格式参数并固定默认 md。
) -> ReportDetailResponse | Response:  # 详情模式返回模型，下载模式返回原始响应。
    if download:  # 如果请求下载文件，
        content, content_type, filename = get_report_export_service(reportId, format)  # 调用服务层获取导出内容、类型和文件名。
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}  # 构造附件下载头，指定文件名。
        return Response(content=content, media_type=content_type, headers=headers)  # 返回下载响应。
    base_url = str(request.base_url).rstrip("/")  # 读取并规范化基础 URL（去掉末尾斜杠）。
    return get_report_detail_service(reportId, base_url)  # 调用服务层返回报表详情。


@router.delete(
    "/reports/{reportId}",
    response_model=DeleteReportResponse,
    summary="删除报表",
    operation_id="deleteReport",
    responses={404: {"model": ErrorResponse}},
)
def delete_report_api(reportId: str) -> DeleteReportResponse:
    try:
        return delete_report_service(reportId)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc