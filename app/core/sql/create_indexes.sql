-- 组合索引：针对最常见的查询 (某栋建筑的某种表在某个时间段的数据)
CREATE INDEX IF NOT EXISTS idx_meters_building_meter_time 
ON meter_readings (building_id, meter, timestamp);

-- 排行和对比查询更常按 meter + 时间过滤，再按 building_id 分组
CREATE INDEX IF NOT EXISTS idx_meters_meter_time_building 
ON meter_readings (meter, timestamp, building_id);

-- 单独的时间索引：针对全系统某个时段的总耗能查询
CREATE INDEX IF NOT EXISTS idx_meters_time 
ON meter_readings (timestamp);

-- 元数据主键索引
CREATE INDEX IF NOT EXISTS idx_metadata_building_id 
ON building_metadata (building_id);

-- 天气数据联合索引 (通过园区+时间联合查询)
CREATE INDEX IF NOT EXISTS idx_weather_site_time 
ON weather_data (site_id, timestamp);
