-- 创建报表主表（不存在时创建），用于存储报表元信息与导出内容。
CREATE TABLE IF NOT EXISTS reports (
    report_id VARCHAR(64) PRIMARY KEY, -- 报表唯一 ID。
    report_type VARCHAR(64) NOT NULL, -- 报表类型（日报/周报/月报/异常报）。
    status VARCHAR(16) NOT NULL, -- 报表状态（queued/processing/ready/failed）。
    building_id VARCHAR(128), -- 报表对应建筑 ID（可空表示聚合）。
    meter VARCHAR(64), -- 报表对应表计类型。
    time_start TIMESTAMPTZ NOT NULL, -- 报表时间范围起点。
    time_end TIMESTAMPTZ NOT NULL, -- 报表时间范围终点。
    include_ai_summary BOOLEAN NOT NULL DEFAULT TRUE, -- 是否开启 AI 总结。
    summary TEXT, -- 报表摘要文本。
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb, -- 报表完整结构化 JSON。
    export_markdown TEXT, -- Markdown 导出缓存内容。
    error_message TEXT, -- 失败时错误信息。
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- 创建时间。
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- 更新时间。
    CONSTRAINT chk_reports_status CHECK (status IN ('queued', 'processing', 'ready', 'failed')), -- 状态约束。
    CONSTRAINT chk_reports_time_range CHECK (time_end >= time_start) -- 时间范围约束。
);

-- 创建按时间倒序查询索引，方便查看最新报表。
CREATE INDEX IF NOT EXISTS idx_reports_created_at
    ON reports (created_at DESC);

-- 创建类型+时间范围组合索引，支持按类型检索。
CREATE INDEX IF NOT EXISTS idx_reports_type_time
    ON reports (report_type, time_start, time_end);

-- 创建建筑+时间范围组合索引，支持按建筑检索。
CREATE INDEX IF NOT EXISTS idx_reports_building_time
    ON reports (building_id, time_start, time_end);
