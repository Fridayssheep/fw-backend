from pydantic import BaseModel
from pydantic import Field

from .schemas_common import Pagination


class KnowledgeDocument(BaseModel):
    document_id: str = Field(..., description="文档 ID")
    dataset_id: str = Field(..., description="所属数据集 ID")
    title: str = Field(..., description="文档标题或文件名")
    category: str = Field(..., description="所属分类，映射自数据集名称")
    source_type: str | None = Field(default=None, description="文件类型，通常由文件后缀推断")
    updated_at: str | None = Field(default=None, description="更新时间 ISO 字符串")
    size: int | None = Field(default=None, description="文件大小，单位字节")


class KnowledgeDocumentListResponse(BaseModel):
    items: list[KnowledgeDocument] = Field(default_factory=list, description="文档列表")
    pagination: Pagination = Field(..., description="分页信息")
    categories_available: list[str] = Field(default_factory=list, description="当前可用分类列表")
