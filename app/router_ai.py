from fastapi import APIRouter
from fastapi import HTTPException

from ai.backend.anomaly_service import analyze_anomaly_with_ai
from ai.backend.feedback_service import submit_anomaly_feedback
from ai.backend.qa_service import ask_ai_question
from ai.backend.query_assistant_service import build_query_intent
from ai.backend.ragflow_client import RagFlowAuthenticationError
from ai.backend.ragflow_client import RagFlowConfigurationError
from ai.backend.ragflow_client import RagFlowInvalidResponseError
from ai.backend.ragflow_client import RagFlowNotFoundError
from ai.backend.ragflow_client import RagFlowTimeoutError
from ai.backend.ragflow_client import RagFlowUpstreamError

from .schemas_ai import AIAnalyzeAnomalyRequest
from .schemas_ai import AIAnalyzeAnomalyResponse
from .schemas_ai import AIQARequest
from .schemas_ai import AIQAResponse
from .schemas_ai import AIQueryAssistantRequest
from .schemas_ai import AIQueryAssistantResponse
from .schemas_ai import AnomalyFeedbackRequest
from .schemas_ai import AnomalyFeedbackResponse


router = APIRouter(tags=["AI"])


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
# 通用知识库 Q&A 接口 - 基于 RAGFlow
# ============================================================================


@router.post("/ai/qa", response_model=AIQAResponse, summary="通用知识/运维库 AI 问答")
def ask_ai_question_api(payload: AIQARequest) -> AIQAResponse:
    """建筑运维/设备知识库 Q&A 接口。

    基于 RAGFlow 知识库（如建筑运维手册、设备使用说明等），
    直接对用户提出的问题进行检索增强生成（RAG），返回知识库中最相关的答案。
    支持会话级别的 session_id 用于维持上下文。
    """
    try:
        return ask_ai_question(payload)
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
