from fastapi import FastAPI  # 导入 FastAPI 应用类。
from fastapi import Request  # 导入 Request，方便在异常处理器里接收原始请求对象。
from fastapi import status  # 导入状态码常量，方便返回统一错误状态码。
from fastapi.responses import JSONResponse  # 导入 JSON 响应类，方便统一返回错误结果。

from .router_buildings import router as buildings_router  # 导入 buildings 分组路由。
from .router_devices import router as devices_router  # 导入 devices 分组路由。
from .router_energy import router as energy_router  # 导入 energy 分组路由。
from .router_system import router as system_router  # 导入 system 分组路由。
from .schemas import ErrorResponse  # 导入统一错误响应模型。
from .service_common import ResourceNotFoundError  # 导入资源不存在异常。


app = FastAPI(  # 创建 FastAPI 应用实例。
    title="Building Energy AI & Backend API",  # 设置接口文档标题。
    version="0.2.0-local-impl",  # 设置当前本地实现版本号。
    description="最小可运行版 system + energy + buildings + devices 接口实现。",  # 设置接口文档描述信息。
)  # 完成应用对象创建。


@app.exception_handler(ResourceNotFoundError)  # 给应用注册资源不存在异常处理器。
def handle_not_found_error(request: Request, exc: ResourceNotFoundError) -> JSONResponse:  # 定义资源不存在异常处理函数。
    return JSONResponse(  # 返回统一错误结构。
        status_code=status.HTTP_404_NOT_FOUND,  # 返回 404 状态码。
        content=ErrorResponse(code="not_found", message=str(exc)).model_dump(mode="json"),  # 把资源不存在错误包装成统一错误结构。
    )  # 完成错误响应返回。


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


app.include_router(system_router)  # 注册 system 分组路由。
app.include_router(buildings_router)  # 注册 buildings 分组路由。
app.include_router(devices_router)  # 注册 devices 分组路由。
app.include_router(energy_router)  # 注册 energy 分组路由。
