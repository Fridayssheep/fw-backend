import asyncio
import os
import shutil
import tempfile

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import File
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from app.core.events import broker
from app.jobs.offline_anomaly_detector import run_batch_pipeline, is_pipeline_running
from app.schemas.schemas_system import RuntimeAISettingsResponse
from app.schemas.schemas_system import RuntimeAISettingsUpdateRequest
from app.schemas.schemas_system import RuntimeAISettingsUpdateResponse
from app.schemas.schemas_system import SystemCurrentTimeRequest
from app.schemas.schemas_system import SystemCurrentTimeResponse
from app.schemas.schemas_system import SystemHealth
from app.services.services_etl import process_metadata_upload
from app.services.services_etl import process_raw_meter_upload
from app.services.services_etl import process_weather_upload
from app.services.services_system import get_system_current_time
from app.services.services_system import get_runtime_ai_settings
from app.services.services_system import get_system_health as get_system_health_service
from app.services.services_system import update_runtime_ai_settings


router = APIRouter(tags=["System"])


@router.get("/health", response_model=SystemHealth, summary="Service health check")
def get_system_health_api() -> SystemHealth:
    return get_system_health_service()


@router.post("/system/current-time", response_model=SystemCurrentTimeResponse, summary="Resolve effective current time")
def get_system_current_time_api(payload: SystemCurrentTimeRequest) -> SystemCurrentTimeResponse:
    return get_system_current_time(payload)


@router.get("/system/ai-settings", response_model=RuntimeAISettingsResponse, summary="Get AI runtime settings")
def get_runtime_ai_settings_api() -> RuntimeAISettingsResponse:
    return get_runtime_ai_settings()


@router.put("/system/ai-settings", response_model=RuntimeAISettingsUpdateResponse, summary="Update AI runtime settings")
def update_runtime_ai_settings_api(payload: RuntimeAISettingsUpdateRequest) -> RuntimeAISettingsUpdateResponse:
    return update_runtime_ai_settings(payload)


@router.get("/dataset/anomaly-progress", summary="Offline anomaly progress stream (SSE)")
async def anomaly_progress_stream_api(request: Request):
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


@router.post("/dataset/trigger-detection", summary="Trigger offline anomaly detection task")
def trigger_anomaly_detection_api(background_tasks: BackgroundTasks) -> dict[str, str]:
    if is_pipeline_running():
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=409,
            content={"status": "conflict", "message": "异常检测任务正在运行中，请等待当前任务完成后再试"}
        )
    background_tasks.add_task(run_batch_pipeline)
    return {"status": "ok", "message": "Anomaly detection task has been queued."}


def _save_upload_file_temp(upload_file: UploadFile) -> str:
    temp_dir = os.path.join(tempfile.gettempdir(), "fw-uploads")
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, upload_file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return file_path


@router.post("/dataset/upload/metadata", summary="Upload and replace building metadata")
def upload_metadata_api(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, str]:
    tmp_path = _save_upload_file_temp(file)
    background_tasks.add_task(process_metadata_upload, tmp_path)
    return {"status": "ok", "message": "Metadata upload accepted and is being processed."}


@router.post("/dataset/upload/weather", summary="Upload and replace weather data")
def upload_weather_api(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, str]:
    tmp_path = _save_upload_file_temp(file)
    background_tasks.add_task(process_weather_upload, tmp_path)
    return {"status": "ok", "message": "Weather upload accepted and is being processed."}


@router.post("/dataset/upload/raw/{meter_type}", summary="Upload raw meter file")
def upload_raw_meter_api(meter_type: str, background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, str]:
    tmp_path = _save_upload_file_temp(file)
    background_tasks.add_task(process_raw_meter_upload, meter_type, tmp_path)
    return {"status": "ok", "message": f"{meter_type} raw upload accepted and is being processed."}
