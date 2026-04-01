from datetime import date  # 瀵煎叆鏃ユ湡绫诲瀷锛屾柟渚垮畾涔夎澶囧畨瑁呮棩鏈熷瓧娈点€?
from datetime import datetime  # 瀵煎叆鏃ユ湡鏃堕棿绫诲瀷锛屾柟渚垮畾涔夋椂闂村瓧娈点€?
from typing import Any  # 瀵煎叆浠绘剰绫诲瀷娉ㄨВ锛屾柟渚跨粰鏉炬暎缁撴瀯鍋氭爣娉ㄣ€?

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


class DeviceSummary(BaseModel):  # 瀹氫箟璁惧鎽樿妯″瀷銆?
    device_id: str  # 瀹氫箟璁惧缂栧彿瀛楁銆?
    device_name: str  # 瀹氫箟璁惧鍚嶇О瀛楁銆?
    device_type: str  # 瀹氫箟璁惧绫诲瀷瀛楁銆?
    building_id: str | None = None  # 瀹氫箟寤虹瓚缂栧彿瀛楁銆?
    status: str  # 瀹氫箟璁惧鐘舵€佸瓧娈点€?


class Device(DeviceSummary):  # 瀹氫箟璁惧璇︽儏妯″瀷銆?
    manufacturer: str | None = None  # 瀹氫箟鍒堕€犲晢瀛楁銆?
    model: str | None = None  # 瀹氫箟鍨嬪彿瀛楁銆?
    install_date: date | None = None  # 瀹氫箟瀹夎鏃ユ湡瀛楁銆?
    last_seen_at: datetime | None = None  # 瀹氫箟鏈€鍚庢椿璺冩椂闂村瓧娈点€?


class DeviceListResponse(BaseModel):  # 瀹氫箟璁惧鍒楄〃鍝嶅簲妯″瀷銆?
    items: list[Device]  # 瀹氫箟璁惧鍒楄〃瀛楁銆?
    pagination: Pagination  # 瀹氫箟鍒嗛〉瀛楁銆?


class DeviceAlarm(BaseModel):  # 瀹氫箟璁惧鍛婅妯″瀷銆?
    alarm_id: str  # 瀹氫箟鍛婅缂栧彿瀛楁銆?
    device_id: str  # 瀹氫箟璁惧缂栧彿瀛楁銆?
    level: str  # 瀹氫箟鍛婅绛夌骇瀛楁銆?
    code: str | None = None  # 瀹氫箟鍛婅浠ｇ爜瀛楁銆?
    message: str  # 瀹氫箟鍛婅娑堟伅瀛楁銆?
    status: str  # 瀹氫箟鍛婅鐘舵€佸瓧娈点€?
    occurred_at: datetime  # 瀹氫箟鍛婅鍙戠敓鏃堕棿瀛楁銆?


class DeviceAlarmListResponse(BaseModel):  # 瀹氫箟璁惧鍛婅鍒楄〃鍝嶅簲妯″瀷銆?
    items: list[DeviceAlarm]  # 瀹氫箟鍛婅鍒楄〃瀛楁銆?
    pagination: Pagination  # 瀹氫箟鍒嗛〉瀛楁銆?


class DeviceDetailResponse(BaseModel):  # 瀹氫箟璁惧璇︽儏鍝嶅簲妯″瀷銆?
    device: Device  # 瀹氫箟璁惧璇︽儏瀛楁銆?
    recent_alarms: list[DeviceAlarm] = Field(default_factory=list)  # 瀹氫箟鏈€杩戝憡璀﹀瓧娈点€?
    recent_metrics: list[MetricCard] = Field(default_factory=list)  # 瀹氫箟鏈€杩戞寚鏍囧瓧娈点€?


class MaintenanceRecord(BaseModel):  # 瀹氫箟缁存姢璁板綍妯″瀷銆?
    record_id: str  # 瀹氫箟璁板綍缂栧彿瀛楁銆?
    device_id: str  # 瀹氫箟璁惧缂栧彿瀛楁銆?
    title: str  # 瀹氫箟缁存姢鏍囬瀛楁銆?
    description: str | None = None  # 瀹氫箟缁存姢鎻忚堪瀛楁銆?
    performed_at: datetime  # 瀹氫箟缁存姢鎵ц鏃堕棿瀛楁銆?


class MaintenanceRecordListResponse(BaseModel):  # 瀹氫箟缁存姢璁板綍鍒楄〃鍝嶅簲妯″瀷銆?
    items: list[MaintenanceRecord]  # 瀹氫箟缁存姢璁板綍鍒楄〃瀛楁銆?
    pagination: Pagination  # 瀹氫箟鍒嗛〉瀛楁銆?


class DetectedAnomalyPoint(BaseModel):  # 瀹氫箟妫€娴嬪埌鐨勫紓甯哥偣妯″瀷銆?
    timestamp: datetime  # 瀹氫箟寮傚父鏃堕棿瀛楁銆?
    actual_value: float  # 瀹氫箟瀹為檯鍊煎瓧娈点€?
    baseline_value: float  # 瀹氫箟鍩虹嚎鍊煎瓧娈点€?
    deviation_rate: float  # 瀹氫箟鍋忕鐜囧瓧娈点€?
    severity: str  # 瀹氫箟涓ラ噸绾у埆瀛楁銆?


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
    session_id: str | None = Field(None, description="会话 ID，用于保持多轮对话上下文")


class AIQAReferenceChunk(BaseModel):
    chunk_id: str | None = Field(None, description="知识片段 ID")
    document_id: str | None = Field(None, description="文档 ID")
    document_name: str | None = Field(None, description="文档名称")
    dataset_id: str | None = Field(None, description="知识库 ID")
    content: str = Field(default="", description="知识片段内容")
    similarity: float | None = Field(None, description="相似度分数")
    metadata: dict[str, Any] = Field(default_factory=dict, description="原始元数据")


class AIQAReferenceDocAgg(BaseModel):
    document_id: str | None = Field(None, description="文档 ID")
    document_name: str | None = Field(None, description="文档名称")
    count: int | None = Field(None, description="命中的片段数量")


class AIQAReference(BaseModel):
    chunks: list[AIQAReferenceChunk] = Field(default_factory=list, description="引用的知识片段")
    doc_aggs: list[AIQAReferenceDocAgg] = Field(default_factory=list, description="按文档聚合的命中信息")


class AIQAMeta(BaseModel):
    provider: str = Field(..., description="上游知识问答服务提供方")
    chat_id: str | None = Field(None, description="RAGFlow Chat ID")
    used_openai_compatible: bool = Field(default=True, description="是否使用 OpenAI-compatible 接口")


class AIQAResponse(BaseModel):
    answer: str = Field(..., description="AI 的回答")
    session_id: str | None = Field(None, description="当前会话 ID")
    references: AIQAReference = Field(default_factory=AIQAReference, description="知识库引用信息")
    meta: AIQAMeta = Field(..., description="调用元信息")
