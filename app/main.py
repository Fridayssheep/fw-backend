from fastapi import FastAPI
from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse

from app.routers.router_ai import router as ai_router
from app.routers.router_buildings import router as buildings_router
from app.routers.router_dashboard import router as dashboard_router
from app.routers.router_meters import router as meters_router
from app.routers.router_energy import router as energy_router
from app.routers.router_system import router as system_router
from .schemas_common import ErrorResponse
from .service_common import ResourceNotFoundError


app = FastAPI(
    title="Building Energy AI & Backend API",
    version="0.3.0-local-impl",
    description="Minimal runnable implementation for system, energy, buildings, meters, and AI routes.",
)


@app.exception_handler(ResourceNotFoundError)
def handle_not_found_error(request: Request, exc: ResourceNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(code="not_found", message=str(exc)).model_dump(mode="json"),
    )


@app.exception_handler(ValueError)
def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(code="validation_error", message=str(exc)).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(code="internal_error", message=str(exc)).model_dump(mode="json"),
    )


app.include_router(system_router)
app.include_router(buildings_router)
app.include_router(dashboard_router)
app.include_router(meters_router)
app.include_router(energy_router)
app.include_router(ai_router)
