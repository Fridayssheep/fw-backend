import asyncio

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import StreamingResponse

from ai.backend.anomaly_service import analyze_anomaly_with_ai
from ai.backend.feedback_service import submit_anomaly_feedback
from ai.backend.ops_guide_service import get_ops_guide
from ai.backend.qa_session_service import delete_session
from ai.backend.qa_service import ask_ai_question
from ai.backend.query_assistant_service import build_query_intent
from ai.backend.report_summary_service import get_report_summary
from ai.backend.ragflow_client import RagFlowAuthenticationError
from ai.backend.ragflow_client import RagFlowConfigurationError
from ai.backend.ragflow_client import RagFlowInvalidResponseError
from ai.backend.ragflow_client import RagFlowNotFoundError
from ai.backend.ragflow_client import RagFlowTimeoutError
from ai.backend.ragflow_client import RagFlowUpstreamError

from app.schemas.schemas_ai import AIAnalyzeAnomalyRequest
from app.schemas.schemas_ai import AIAnalyzeAnomalyResponse
from app.schemas.schemas_ai import AIOpsGuideRequest
from app.schemas.schemas_ai import AIOpsGuideResponse
from app.schemas.schemas_ai import AIQARequest
from app.schemas.schemas_ai import AIQAResponse
from app.schemas.schemas_ai import AIQASessionDeleteResponse
from app.schemas.schemas_ai import AIQueryAssistantRequest
from app.schemas.schemas_ai import AIQueryAssistantResponse
from app.schemas.schemas_ai import AIReportSummaryRequest
from app.schemas.schemas_ai import AIReportSummaryResponse
from app.schemas.schemas_ai import AnomalyFeedbackRequest
from app.schemas.schemas_ai import AnomalyFeedbackResponse
from app.schemas.schemas_common import ErrorResponse
from app.services.service_common import ResourceNotFoundError

from app.core.events import broker


router = APIRouter(tags=["AI"])

@router.get("/ai/status", summary="旁路状态推流 (SSE)")
async def ai_status_stream_api(request: Request):
    """
    让前端在请求耗时接口前，建立此 EventSource 的单向监听。
    后端会在调用底层各种工具时自动向此流推送状态更新。
    """
    async def event_generator():
        q = broker.add_client()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # 使用 1 秒超时打断等待，以便及时循环检测客户端断开状态
                    data = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    continue
        finally:
            broker.remove_client(q)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ============================================================================
# AI 异常分析接口
# ============================================================================

@router.post("/ai/analyze-anomaly", response_model=AIAnalyzeAnomalyResponse, summary="AI anomaly analysis")
def analyze_anomaly_api(payload: AIAnalyzeAnomalyRequest) -> AIAnalyzeAnomalyResponse:
    """AI 异常分析接口。

    通过调用后端能耗异常检测、天气相关性分析、历史反馈检索等模块，
    结合 LLM 能力进行建筑能耗异常的诊断，返回候选根因、证据、建议行动等结构化分析结果。
    """

    return analyze_anomaly_with_ai(payload)


# ============================================================================
# 查询助手接口 - 将自然语言查询转换为结构化查询意图
# ============================================================================


@router.post("/ai/query-assistant", response_model=AIQueryAssistantResponse, summary="Parse query intent")
def query_assistant_api(payload: AIQueryAssistantRequest) -> AIQueryAssistantResponse:
    """查询意图解析接口。

    接受自然语言能源查询问题，通过规则和 LLM 的组合方式解析为结构化查询意图，
    包括建筑 ID、表计类型、时间范围、粒度等参数，并推荐合适的后端查询 API 端点和 HTTP 方法。
    """

    return build_query_intent(payload)


# ============================================================================
# 异常分析反馈接口
# ============================================================================


@router.post("/ai/anomaly-feedback", response_model=AnomalyFeedbackResponse, summary="Submit anomaly feedback")
def submit_anomaly_feedback_api(payload: AnomalyFeedbackRequest) -> AnomalyFeedbackResponse:
    """异常分析反馈提交接口。

    用户对 AI 异常分析结果的反馈，包括反馈得分、选定的根因、备注意见等，
    这些反馈将被保存到数据库，用于改进未来的异常分析准确度和检验 LLM 效果。
    """

    return submit_anomaly_feedback(payload)


# ============================================================================
# 运维指导接口
# ============================================================================


@router.post("/ai/ops-guide", response_model=AIOpsGuideResponse, summary="AI 运维指导")
def get_ai_ops_guide_api(payload: AIOpsGuideRequest) -> AIOpsGuideResponse:
    """接手故障后的 AI 运维指导接口。

    前端只需要传递当前页面已知的最小上下文，后端会在内部补全 ops_context，
    复用异常分析、知识检索和历史反馈能力，输出步骤化运维指导。
    """
    try:
        return get_ops_guide(payload)
    except RagFlowConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RagFlowAuthenticationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagFlowNotFoundError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagFlowTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (RagFlowUpstreamError, RagFlowInvalidResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================================
# AI 报表总结接口
# ============================================================================


@router.post("/ai/report-summary", response_model=AIReportSummaryResponse, summary="AI 报表总结")
def get_ai_report_summary_api(payload: AIReportSummaryRequest) -> AIReportSummaryResponse:
    """AI 报表总结接口。

    前端只需要传递当前页面已知的最小报表素材，后端会在内部补全 report_context，
    结合可选的异常洞察生成结构化摘要、亮点、风险和建议动作。
    """
    try:
        return get_report_summary(payload)
    except RagFlowConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RagFlowAuthenticationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagFlowNotFoundError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagFlowTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (RagFlowUpstreamError, RagFlowInvalidResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================================
# 总览式 AI 问答入口
# ============================================================================


@router.post("/ai/qa", response_model=AIQAResponse, summary="总览式 AI 问答入口")
def ask_ai_question_api(payload: AIQARequest) -> AIQAResponse:
    """总览式 AI 问答接口。

    统一接收用户问题，并根据问题类型自主选择知识检索、查询意图解析、
    异常分析等能力，再把答案、证据引用、已使用工具和建议动作统一返回给前端。
    """
    try:
        return ask_ai_question(payload)
    except ValueError as exc:
        if str(exc).startswith("qa session not found:"):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RagFlowConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RagFlowAuthenticationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagFlowNotFoundError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagFlowTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (RagFlowUpstreamError, RagFlowInvalidResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete(
    "/ai/qa/sessions/{sessionId}",
    response_model=AIQASessionDeleteResponse,
    summary="删除 AI 历史会话",
    responses={404: {"model": ErrorResponse}},
)
def delete_ai_qa_session_api(sessionId: str) -> AIQASessionDeleteResponse:
    """删除一个 AI 历史会话，并级联清理对应消息记录。"""

    try:
        return delete_session(sessionId)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
