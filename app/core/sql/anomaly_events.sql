CREATE TABLE IF NOT EXISTS anomaly_events (
    id SERIAL PRIMARY KEY,
    building_id VARCHAR(128) NOT NULL,
    site_id VARCHAR(128),
    meter VARCHAR(64) NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    peak_deviation FLOAT,
    severity VARCHAR(32),
    detected_by VARCHAR(64),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_building_time ON anomaly_events(building_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_anomaly_events_meter_time ON anomaly_events(meter, start_time, end_time);
