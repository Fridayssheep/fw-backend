-- Dashboard 与能耗高频查询使用该日聚合表，避免反复扫描 meter_readings 明细表。
-- 聚合粒度为「天 + 建筑 + meter」，用于趋势图与双周期统计等场景。
CREATE TABLE IF NOT EXISTS meter_daily_agg (
    bucket_day DATE NOT NULL,
    building_id VARCHAR(128) NOT NULL,
    meter VARCHAR(64) NOT NULL,
    reading_sum DOUBLE PRECISION NOT NULL DEFAULT 0,
    reading_count BIGINT NOT NULL DEFAULT 0,
    latest_timestamp TIMESTAMP,
    refreshed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bucket_day, building_id, meter)
);
