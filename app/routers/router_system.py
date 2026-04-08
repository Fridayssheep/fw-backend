import asyncio
import os
import shutil
import tempfile

from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Request  # 导入 APIRouter, 后台任务和上传必要组件
from fastapi.responses import StreamingResponse

from app.schemas.schemas_system import SystemHealth  # 导入健康检查响应模型。
from app.services.services_system import get_system_health as get_system_health_service  # 导入 system 领域的健康检查业务函数。
from app.jobs.offline_anomaly_detector import run_batch_pipeline
from app.services.services_etl import process_metadata_upload, process_weather_upload, process_raw_meter_upload
from app.core.events import broker


router = APIRouter(tags=["System"])  # 创建 system 分组路由对象，并统一设置文档标签。


@router.get("/health", response_model=SystemHealth, summary="服务健康检查")  # 注册 system 健康检查接口。
def get_system_health_api() -> SystemHealth:  # 定义健康检查接口处理函数。
    return get_system_health_service()  # 调用 system 业务层并返回结果。

@router.get("/dataset/anomaly-progress-stream", summary="离线跑批进度推流 (SSE)")
async def anomaly_progress_stream_api(request: Request):
    """
    提供给前端用来监听离线跑批进度的接口。
    前端可以通过 EventSource 收到实时的进度推送和当前分析的大楼编号。
    """
    async def event_generator():
        q = broker.add_client()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    continue
        finally:
            broker.remove_client(q)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/dataset/trigger-detection", summary="手动触发后台离线异常跑批任务")
def trigger_anomaly_detection_api(background_tasks: BackgroundTasks) -> dict[str, str]:
    """触发后台并行离线异常跑批诊断任务，该接口立即返回，由 FastAPI 背景任务在后台执行。"""
    background_tasks.add_task(run_batch_pipeline)
    return {"status": "ok", "message": "异常检测任务已加入队列并在后台并发执行。"}

def _save_upload_file_temp(upload_file: UploadFile) -> str:
    """内部通用函数，将上传的文件临时存放以供 Pandas 读取。"""
    temp_dir = os.path.join(tempfile.gettempdir(), "fw-uploads")
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, upload_file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return file_path


@router.post("/dataset/upload/metadata", summary="上传并覆写建筑元数据")
def upload_metadata_api(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, str]:
    """接收 CSV 文件并覆写建筑基础信息（不会破坏已有表计流结构）。该接口不阻塞前台请求。"""
    tmp_path = _save_upload_file_temp(file)
    background_tasks.add_task(process_metadata_upload, tmp_path)
    return {"status": "ok", "message": "上传元数据成功，开始处理建筑元数据..."}


@router.post("/dataset/upload/weather", summary="上传覆盖本区域天气数据")
def upload_weather_api(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, str]:
    """接收 CSV 文件并覆盖天气数据仓库（独立于基建及能耗线）。该接口不阻塞前台。"""
    tmp_path = _save_upload_file_temp(file)
    background_tasks.add_task(process_weather_upload, tmp_path)
    return {"status": "ok", "message": "上传天气数据成功，开始处理天气数据..."}


@router.post("/dataset/upload/raw/{meter_type}", summary="单点上传覆盖/追加表计流水")
def upload_raw_meter_api(meter_type: str, background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, str]:
    """接收宽表 CSV 文件。系统将独立对此文件执行 0 值和卡断清洗，纵向解包追加至总库并**触发该表类型的异常排查算法**。"""
    tmp_path = _save_upload_file_temp(file)
    background_tasks.add_task(process_raw_meter_upload, meter_type, tmp_path)
    return {"status": "ok", "message": f"{meter_type} 表计宽表已接受，正在后台进行全量清洗降维与智能异常巡检分析..."}
