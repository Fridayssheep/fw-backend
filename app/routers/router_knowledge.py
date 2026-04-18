from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import Response

from ai.backend.ragflow_client import RagFlowAuthenticationError
from ai.backend.ragflow_client import RagFlowConfigurationError
from ai.backend.ragflow_client import RagFlowInvalidResponseError
from ai.backend.ragflow_client import RagFlowNotFoundError
from ai.backend.ragflow_client import RagFlowTimeoutError
from ai.backend.ragflow_client import RagFlowUpstreamError

from app.schemas.schemas_common import ErrorResponse
from app.schemas.schemas_knowledge import KnowledgeDocumentListResponse
from app.services.service_common import ResourceNotFoundError
from app.services.services_knowledge import download_knowledge_document
from app.services.services_knowledge import list_knowledge_documents


router = APIRouter(tags=["Knowledge"])


@router.get(
    "/knowledge/documents",
    response_model=KnowledgeDocumentListResponse,
    summary="获取知识库文档聚合列表",
    responses={
        400: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
def list_knowledge_documents_api(
    keyword: str | None = Query(default=None),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> KnowledgeDocumentListResponse:
    try:
        return list_knowledge_documents(
            keyword=keyword,
            category=category,
            page=page,
            page_size=page_size,
        )
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


@router.get(
    "/knowledge/datasets/{dataset_id}/documents/{document_id}/download",
    summary="下载知识库文档",
    responses={
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
def download_knowledge_document_api(dataset_id: str, document_id: str) -> Response:
    try:
        result = download_knowledge_document(dataset_id, document_id)
        return Response(
            content=result.content,
            media_type=result.media_type,
            headers={"Content-Disposition": result.content_disposition},
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RagFlowConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RagFlowAuthenticationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagFlowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RagFlowTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (RagFlowUpstreamError, RagFlowInvalidResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
