from datetime import date  # 导入日期类型，方便定义设备安装日期字段。
from datetime import datetime  # 导入日期时间类型，方便定义时间字段。
from enum import Enum  # 导入枚举类型，方便约束 meter 相关状态字段。
from typing import Any  # 导入任意类型注解，方便给松散结构做标注。

from pydantic import BaseModel  # 瀵煎叆 Pydantic 鍩虹被锛岀敤鏉ュ畾涔夋帴鍙ｆā鍨嬨€?
from pydantic import Field  # 瀵煎叆瀛楁瀹氫箟鍑芥暟锛屾柟渚跨粰瀛楁璁剧疆榛樿鍊笺€?


class ErrorResponse(BaseModel):  # 瀹氫箟缁熶竴閿欒鍝嶅簲妯″瀷銆?
    code: str  # 瀹氫箟閿欒鐮佸瓧娈点€?
    message: str  # 瀹氫箟閿欒淇℃伅瀛楁銆?


class SystemHealth(BaseModel):  # 瀹氫箟鍋ュ悍妫€鏌ュ搷搴旀ā鍨嬨€?
    status: str  # 瀹氫箟鏈嶅姟鐘舵€佸瓧娈点€?
    database: str  # 瀹氫箟鏁版嵁搴撶姸鎬佸瓧娈点€?
    timestamp: datetime  # 瀹氫箟鍝嶅簲鏃堕棿瀛楁銆?


class TimeRange(BaseModel):  # 瀹氫箟鏃堕棿鑼冨洿妯″瀷銆?
    start: datetime  # 瀹氫箟寮€濮嬫椂闂村瓧娈点€?
    end: datetime  # 瀹氫箟缁撴潫鏃堕棿瀛楁銆?


class Pagination(BaseModel):  # 瀹氫箟鍒嗛〉妯″瀷銆?
    page: int  # 瀹氫箟椤电爜瀛楁銆?
    page_size: int  # 瀹氫箟姣忛〉鏉℃暟瀛楁銆?
    total: int  # 瀹氫箟鎬绘潯鏁板瓧娈点€?


class MeterAvailability(BaseModel):  # 瀹氫箟寤虹瓚琛ㄨ鍙敤鎬фā鍨嬨€?
    meter: str  # 瀹氫箟琛ㄨ绫诲瀷瀛楁銆?
    available: bool  # 瀹氫箟鏄惁鍙敤瀛楁銆?


class MetricCard(BaseModel):  # 瀹氫箟閫氱敤鎸囨爣鍗＄墖妯″瀷銆?
    key: str  # 瀹氫箟鎸囨爣閿瓧娈点€?
    label: str  # 瀹氫箟鎸囨爣鍚嶇О瀛楁銆?
    value: float  # 瀹氫箟鎸囨爣鍊煎瓧娈点€?
    unit: str | None = None  # 瀹氫箟鎸囨爣鍗曚綅瀛楁銆?
    change_rate: float | None = None  # 瀹氫箟鍙樺寲鐜囧瓧娈点€?


class Building(BaseModel):  # 瀹氫箟寤虹瓚鍩虹淇℃伅妯″瀷銆?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    site_id: str  # 瀹氫箟鍥尯缂栧彿瀛楁銆?
    primaryspaceusage: str  # 瀹氫箟涓昏鐢ㄩ€斿瓧娈点€?
    sub_primaryspaceusage: str | None = None  # 瀹氫箟娆＄骇鐢ㄩ€斿瓧娈点€?
    sqm: float | None = None  # 瀹氫箟寤虹瓚闈㈢Н瀛楁銆?
    lat: float | None = None  # 瀹氫箟绾害瀛楁銆?
    lng: float | None = None  # 瀹氫箟缁忓害瀛楁銆?
    timezone: str | None = None  # 瀹氫箟鏃跺尯瀛楁銆?
    yearbuilt: int | None = None  # 瀹氫箟寤烘垚骞翠唤瀛楁銆?
    leed_level: str | None = None  # 瀹氫箟 LEED 绛夌骇瀛楁銆?


class BuildingListResponse(BaseModel):  # 瀹氫箟寤虹瓚鍒楄〃鍝嶅簲妯″瀷銆?
    items: list[Building]  # 瀹氫箟寤虹瓚鍒楄〃瀛楁銆?
    pagination: Pagination  # 瀹氫箟鍒嗛〉瀛楁銆?


class BuildingDetailResponse(BaseModel):  # 瀹氫箟寤虹瓚璇︽儏鍝嶅簲妯″瀷銆?
    building: Building  # 瀹氫箟寤虹瓚淇℃伅瀛楁銆?
    meters: list[MeterAvailability]  # 瀹氫箟琛ㄨ鍙敤鎬у垪琛ㄥ瓧娈点€?
    summary_metrics: list[MetricCard] = Field(default_factory=list)  # 瀹氫箟鎽樿鎸囨爣鍗＄墖瀛楁銆?


class EnergyPoint(BaseModel):  # 瀹氫箟鍗曚釜鑳借€楃偣妯″瀷銆?
    timestamp: datetime  # 瀹氫箟鏃堕棿鐐瑰瓧娈点€?
    building_id: str | None = None  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    meter: str | None = None  # 瀹氫箟琛ㄨ绫诲瀷瀛楁銆?
    value: float  # 瀹氫箟鑳借€楀€煎瓧娈点€?


class EnergySummary(BaseModel):  # 瀹氫箟鑳借€楁眹鎬绘ā鍨嬨€?
    meter: str  # 瀹氫箟琛ㄨ绫诲瀷瀛楁銆?
    total: float  # 瀹氫箟鎬昏兘鑰楀瓧娈点€?
    average: float  # 瀹氫箟骞冲潎鑳借€楀瓧娈点€?
    peak: float  # 瀹氫箟宄板€艰兘鑰楀瓧娈点€?
    peak_time: datetime | None = None  # 瀹氫箟宄板€兼椂闂村瓧娈点€?
    unit: str | None = None  # 瀹氫箟鍗曚綅瀛楁銆?


class EnergySummaryResponse(BaseModel):  # 瀹氫箟寤虹瓚绾ц兘鑰楁憳瑕佸搷搴旀ā鍨嬨€?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    time_range: TimeRange  # 瀹氫箟鏃堕棿鑼冨洿瀛楁銆?
    summary: EnergySummary  # 瀹氫箟鑳借€楁憳瑕佸瓧娈点€?


class EnergyQueryResponse(BaseModel):  # 瀹氫箟鑳借€楁槑缁嗘煡璇㈠搷搴旀ā鍨嬨€?
    items: list[EnergyPoint]  # 瀹氫箟鏄庣粏鏁版嵁鍒楄〃瀛楁銆?
    summary: EnergySummary  # 瀹氫箟鎽樿瀛楁銆?
    pagination: Pagination | None = None  # 瀹氫箟鍒嗛〉瀛楁銆?


class EnergySeries(BaseModel):  # 瀹氫箟瓒嬪娍搴忓垪妯″瀷銆?
    building_id: str | None = None  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    meter: str  # 瀹氫箟琛ㄨ绫诲瀷瀛楁銆?
    unit: str | None = None  # 瀹氫箟鍗曚綅瀛楁銆?
    points: list[EnergyPoint]  # 瀹氫箟鐐逛綅鍒楄〃瀛楁銆?


class EnergyTrendResponse(BaseModel):  # 瀹氫箟瓒嬪娍鍝嶅簲妯″瀷銆?
    time_range: TimeRange  # 瀹氫箟鏃堕棿鑼冨洿瀛楁銆?
    series: list[EnergySeries]  # 瀹氫箟瓒嬪娍搴忓垪瀛楁銆?


class EnergyCompareItem(BaseModel):  # 瀹氫箟瀵规瘮椤规ā鍨嬨€?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    metric: str  # 瀹氫箟瀵规瘮鎸囨爣瀛楁銆?
    value: float  # 瀹氫箟瀵规瘮鍊煎瓧娈点€?
    unit: str | None = None  # 瀹氫箟鍗曚綅瀛楁銆?


class EnergyCompareResponse(BaseModel):  # 瀹氫箟瀵规瘮鍝嶅簲妯″瀷銆?
    items: list[EnergyCompareItem]  # 瀹氫箟瀵规瘮缁撴灉鍒楄〃瀛楁銆?


class EnergyRankingItem(BaseModel):  # 瀹氫箟鎺掕椤规ā鍨嬨€?
    rank: int  # 瀹氫箟鎺掑悕瀛楁銆?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    value: float  # 瀹氫箟鎺掕鍊煎瓧娈点€?
    unit: str | None = None  # 瀹氫箟鍗曚綅瀛楁銆?


class EnergyRankingResponse(BaseModel):  # 瀹氫箟鎺掕鍝嶅簲妯″瀷銆?
    items: list[EnergyRankingItem]  # 瀹氫箟鎺掕缁撴灉鍒楄〃瀛楁銆?


class CopPoint(BaseModel):  # 瀹氫箟 COP 鍗曠偣妯″瀷銆?
    timestamp: datetime  # 瀹氫箟鏃堕棿鐐瑰瓧娈点€?
    cop: float  # 瀹氫箟 COP 鏁板€煎瓧娈点€?


class CopSummary(BaseModel):  # 瀹氫箟 COP 鎽樿妯″瀷銆?
    avg_cop: float  # 瀹氫箟骞冲潎 COP 瀛楁銆?
    min_cop: float  # 瀹氫箟鏈€灏?COP 瀛楁銆?
    max_cop: float  # 瀹氫箟鏈€澶?COP 瀛楁銆?
    calculation_mode: str  # 瀹氫箟璁＄畻妯″紡瀛楁銆?
    formula: str  # 瀹氫箟鍏紡璇存槑瀛楁銆?


class CopAnalysisResponse(BaseModel):  # 瀹氫箟 COP 鍝嶅簲妯″瀷銆?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    time_range: TimeRange  # 瀹氫箟鏃堕棿鑼冨洿瀛楁銆?
    points: list[CopPoint]  # 瀹氫箟 COP 鐐逛綅鍒楄〃瀛楁銆?
    summary: CopSummary | dict[str, Any] | None = None  # 瀹氫箟鎽樿瀛楁锛屽悓鏃跺吋瀹规枃妗ｉ噷鐨?object銆?


class WeatherPoint(BaseModel):  # 瀹氫箟澶╂皵鐐规ā鍨嬨€?
    timestamp: datetime  # 瀹氫箟鏃堕棿鐐瑰瓧娈点€?
    air_temperature: float | None = None  # 瀹氫箟姘旀俯瀛楁銆?
    dew_temperature: float | None = None  # 瀹氫箟闇茬偣娓╁害瀛楁銆?
    wind_speed: float | None = None  # 瀹氫箟椋庨€熷瓧娈点€?


class WeatherFactor(BaseModel):  # 瀹氫箟澶╂皵鐩稿叧鍥犲瓙妯″瀷銆?
    name: str  # 瀹氫箟鍥犲瓙鍚嶇О瀛楁銆?
    coefficient: float  # 瀹氫箟鐩稿叧绯绘暟瀛楁銆?
    direction: str  # 瀹氫箟姝ｈ礋鏂瑰悜瀛楁銆?


class WeatherCorrelationResponse(BaseModel):  # 瀹氫箟澶╂皵鐩稿叧鎬у搷搴旀ā鍨嬨€?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    meter: str  # 瀹氫箟琛ㄨ绫诲瀷瀛楁銆?
    correlation_coefficient: float  # 瀹氫箟涓荤浉鍏崇郴鏁板瓧娈点€?
    factors: list[WeatherFactor] = Field(default_factory=list)  # 瀹氫箟鍥犲瓙鍒楄〃瀛楁銆?


class MeterStatus(str, Enum):  # 定义表计状态枚举。
    online = "online"  # 定义在线状态。
    warning = "warning"  # 定义告警状态。
    fault = "fault"  # 定义故障状态。
    offline = "offline"  # 定义离线状态。


class MeterSummary(BaseModel):  # 定义表计摘要模型。
    meter_id: str  # 定义表计编号字段。
    meter_name: str  # 定义表计名称字段。
    meter_type: str  # 定义表计类型字段。
    building_id: str | None = None  # 定义建筑编号字段。
    status: MeterStatus  # 定义表计状态字段。


class Meter(MeterSummary):  # 定义表计详情模型。
    manufacturer: str | None = None  # 定义制造商字段。
    model: str | None = None  # 定义型号字段。
    install_date: date | None = None  # 定义安装日期字段。
    last_seen_at: datetime | None = None  # 定义最后活跃时间字段。


class MeterListResponse(BaseModel):  # 定义表计列表响应模型。
    items: list[Meter]  # 定义表计列表字段。
    pagination: Pagination  # 定义分页字段。


class MeterAlarmLevel(str, Enum):  # 定义表计告警等级枚举。
    info = "info"  # 定义提示级告警。
    warning = "warning"  # 定义警告级告警。
    critical = "critical"  # 定义严重级告警。


class MeterAlarmStatus(str, Enum):  # 定义表计告警状态枚举。
    open = "open"  # 定义未关闭状态。
    closed = "closed"  # 定义已关闭状态。


class MeterAlarm(BaseModel):  # 定义表计告警模型。
    alarm_id: str  # 定义告警编号字段。
    meter_id: str  # 定义表计编号字段。
    level: MeterAlarmLevel  # 定义告警等级字段。
    code: str | None = None  # 定义告警代码字段。
    message: str  # 定义告警消息字段。
    status: MeterAlarmStatus  # 定义告警状态字段。
    occurred_at: datetime  # 定义告警发生时间字段。


class MeterAlarmListResponse(BaseModel):  # 定义表计告警列表响应模型。
    items: list[MeterAlarm]  # 定义告警列表字段。
    pagination: Pagination  # 定义分页字段。


class MeterDetailResponse(BaseModel):  # 定义表计详情响应模型。
    meter: Meter  # 定义表计详情字段。
    recent_alarms: list[MeterAlarm] = Field(default_factory=list)  # 定义最近告警字段。
    recent_metrics: list[MetricCard] = Field(default_factory=list)  # 定义最近指标字段。


class MaintenanceRecord(BaseModel):  # 定义维护记录模型。
    record_id: str  # 定义记录编号字段。
    meter_id: str  # 定义表计编号字段。
    title: str  # 定义维护标题字段。
    description: str | None = None  # 定义维护描述字段。
    performed_at: datetime  # 定义维护执行时间字段。


class MaintenanceRecordListResponse(BaseModel):  # 定义维护记录列表响应模型。
    items: list[MaintenanceRecord]  # 定义维护记录列表字段。
    pagination: Pagination  # 定义分页字段。


# 兼容旧的 device 命名，避免其他模块导入路径立刻失效。
DeviceSummary = MeterSummary
Device = Meter
DeviceListResponse = MeterListResponse
DeviceAlarm = MeterAlarm
DeviceAlarmListResponse = MeterAlarmListResponse
DeviceDetailResponse = MeterDetailResponse


class DetectedAnomalyPoint(BaseModel):  # 定义检测到的异常点模型。
    timestamp: datetime  # 定义异常时间字段。
    actual_value: float  # 定义实际值字段。
    baseline_value: float  # 定义基线值字段。
    deviation_rate: float  # 定义偏离率字段。
    severity: str  # 定义严重级别字段。


class EnergyAnomalyAnalysisRequest(BaseModel):  # 瀹氫箟寮傚父鍒嗘瀽璇锋眰妯″瀷銆?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    meter: str  # 瀹氫箟琛ㄨ绫诲瀷瀛楁銆?
    time_range: TimeRange  # 瀹氫箟鏃堕棿鑼冨洿瀛楁銆?
    granularity: str | None = "hour"  # 瀹氫箟绮掑害瀛楁锛岄粯璁ゆ寜灏忔椂鍒嗘瀽銆?
    baseline_mode: str | None = "overall_mean"  # 瀹氫箟鍩虹嚎妯″紡瀛楁锛岄粯璁ゆ暣浣撳潎鍊笺€?
    include_weather_context: bool | None = False  # 瀹氫箟鏄惁杩斿洖澶╂皵涓婁笅鏂囧瓧娈点€?


class EnergyAnomalyAnalysisResponse(BaseModel):  # 瀹氫箟寮傚父鍒嗘瀽鍝嶅簲妯″瀷銆?
    building_id: str  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    meter: str  # 瀹氫箟琛ㄨ绫诲瀷瀛楁銆?
    time_range: TimeRange  # 瀹氫箟鏃堕棿鑼冨洿瀛楁銆?
    is_anomalous: bool  # 瀹氫箟鏄惁瀛樺湪寮傚父瀛楁銆?
    summary: str  # 瀹氫箟鎽樿璇存槑瀛楁銆?
    baseline_mode: str  # 瀹氫箟鍩虹嚎妯″紡瀛楁銆?
    detected_points: list[DetectedAnomalyPoint]  # 瀹氫箟寮傚父鐐瑰垪琛ㄥ瓧娈点€?
    series: EnergySeries  # 瀹氫箟鐢ㄤ簬鍒嗘瀽鐨勫師濮嬪簭鍒楀瓧娈点€?
    weather_context: list[WeatherPoint] | None = None  # 瀹氫箟澶╂皵涓婁笅鏂囧瓧娈点€?

class AIActionItem(BaseModel):
    label: str
    action_type: str
    target: str
    target_id: str | None = None


class AIEvidenceItem(BaseModel):
    evidence_id: str
    type: str
    source: str
    snippet: str
    weight: float | None = None


class AICandidateCause(BaseModel):
    cause_id: str
    title: str
    description: str
    confidence: float
    rank: int
    recommended_checks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class AIFeedbackPrompt(BaseModel):
    enabled: bool = True
    message: str
    allow_score: bool = True
    allow_comment: bool = True


class AIAnalyzeAnomalyMeta(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    baseline_mode: str
    generated_at: datetime
    model: str
    knowledge_hits: int = 0
    history_feedback_hits: int = 0
    used_fallback: bool = False


class AIAnalyzeAnomalyRequest(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    granularity: str | None = "hour"
    baseline_mode: str | None = "overall_mean"
    include_weather_context: bool = False
    question: str | None = None
    include_history_feedback: bool = True
    max_candidate_causes: int = 3


class AIAnalyzeAnomalyResponse(BaseModel):
    analysis_id: str
    status: str
    summary: str
    answer: str
    candidate_causes: list[AICandidateCause]
    highlights: list[str] = Field(default_factory=list)
    evidence: list[AIEvidenceItem] = Field(default_factory=list)
    actions: list[AIActionItem] = Field(default_factory=list)
    risk_notice: str
    feedback_prompt: AIFeedbackPrompt
    meta: AIAnalyzeAnomalyMeta


class AIQueryIntent(BaseModel):
    building_ids: list[str] = Field(default_factory=list)
    site_id: str | None = None
    meter: str | None = None
    time_range: TimeRange | None = None
    granularity: str | None = None
    aggregation: str | None = None
    metric: str | None = None
    limit: int | None = None


class AIQueryAssistantRequest(BaseModel):
    question: str
    current_time: datetime | None = None


class AIQueryAssistantMeta(BaseModel):
    generated_at: datetime
    model: str
    used_fallback: bool = False


class AIQueryAssistantResponse(BaseModel):
    summary: str
    query_intent: AIQueryIntent
    recommended_endpoint: str
    recommended_http_method: str
    recommended_query_params: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    meta: AIQueryAssistantMeta

class CandidateFeedbackItem(BaseModel):
    cause_id: str
    score: int
    title: str | None = None


class SelectedCauseSummary(BaseModel):
    cause_id: str
    title: str
    score: int


class AnomalyFeedbackMeta(BaseModel):
    building_id: str
    meter: str
    resolution_status: str
    created_at: datetime


class AnomalyFeedbackRequest(BaseModel):
    analysis_id: str
    building_id: str
    meter: str
    time_range: TimeRange
    selected_cause_id: str
    selected_score: int
    selected_cause_title: str | None = None
    candidate_feedbacks: list[CandidateFeedbackItem] = Field(default_factory=list)
    comment: str | None = None
    operator_id: str | None = None
    operator_name: str | None = None
    resolution_status: str
    model_name: str | None = None
    baseline_mode: str | None = None


class AnomalyFeedbackResponse(BaseModel):
    feedback_id: str
    analysis_id: str
    stored: bool
    message: str
    selected_cause: SelectedCauseSummary
    meta: AnomalyFeedbackMeta

class AIQARequest(BaseModel):
    question: str = Field(..., description="用户提出的问题")
    session_id: str | None = Field(None, description="前端侧会话 ID，用于自行维持会话上下文")
    context: "AIQAContext | None" = Field(None, description="当前页面和业务对象上下文")


class AIQAContext(BaseModel):
    page: str | None = Field(None, description="当前页面标识，例如 dashboard、device_detail、anomaly_detail")
    building_id: str | None = Field(None, description="当前建筑 ID")
    device_id: str | None = Field(None, description="当前设备 ID")
    anomaly_id: str | None = Field(None, description="当前异常 ID")
    meter: str | None = Field(None, description="当前表计类型")
    time_range: TimeRange | None = Field(None, description="当前页面绑定的时间范围")


class AIReferenceItem(BaseModel):
    source_type: str = Field(..., description="证据来源类型：knowledge / data / history_case")
    document_id: str | None = Field(None, description="来源对象 ID")
    document_name: str | None = Field(None, description="文档名、图表名或案例标题")
    chunk_id: str | None = Field(None, description="知识片段 ID；若不是知识库来源可为空")
    snippet: str = Field(..., description="给前端展示的精简证据摘要")
    score: float | None = Field(None, description="可选分值，例如检索相似度或证据权重")


class AIQAReferences(BaseModel):
    knowledge: list[AIReferenceItem] = Field(default_factory=list, description="知识库证据")
    data: list[AIReferenceItem] = Field(default_factory=list, description="数据查询或图表类证据")
    history_cases: list[AIReferenceItem] = Field(default_factory=list, description="历史反馈或历史案例证据")


class AIUsedToolItem(BaseModel):
    tool_name: str = Field(..., description="实际调用的工具名")
    tool_type: str = Field(..., description="工具类型：mcp / backend_api / internal_service / llm")
    reason: str | None = Field(None, description="调用该工具的原因说明")


class AISuggestedAction(BaseModel):
    label: str = Field(..., description="给前端展示的动作名称")
    action_type: str = Field(..., description="动作类型：open_page / call_api / view_reference / none")
    target: str | None = Field(None, description="动作目标标识，由前端自行映射")


class AIQAMeta(BaseModel):
    provider: str = Field(..., description="本次回答的总体提供方式，例如 orchestrated")
    model: str | None = Field(None, description="最终生成答案的模型名")
    generated_at: datetime = Field(..., description="生成时间")
    used_tools_count: int = Field(default=0, description="本次实际调用的工具数量")
    has_references: bool = Field(default=False, description="本次回答是否附带证据引用")


class AIQAResponse(BaseModel):
    answer: str = Field(..., description="AI 的回答")
    question_type: str = Field(..., description="问题类型：knowledge / fault_analysis / data_query / mixed / other")
    references: AIQAReferences = Field(default_factory=AIQAReferences, description="统一证据引用信息")
    used_tools: list[AIUsedToolItem] = Field(default_factory=list, description="本次回答实际使用的工具")
    suggested_actions: list[AISuggestedAction] = Field(default_factory=list, description="前端可选后续动作")
    meta: AIQAMeta = Field(..., description="调用元信息")


AIQARequest.model_rebuild()
