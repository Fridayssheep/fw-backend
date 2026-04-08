-- Core business tables for fresh database bootstrap.
-- Keep these table definitions compatible with current upload CSV headers.

CREATE TABLE IF NOT EXISTS building_metadata (
    building_id VARCHAR(128) PRIMARY KEY,
    site_id VARCHAR(128),
    building_id_kaggle VARCHAR(128),
    site_id_kaggle VARCHAR(128),
    primaryspaceusage VARCHAR(255),
    sub_primaryspaceusage VARCHAR(255),
    sqm DOUBLE PRECISION,
    sqft DOUBLE PRECISION,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    timezone VARCHAR(128),
    electricity VARCHAR(32),
    hotwater VARCHAR(32),
    chilledwater VARCHAR(32),
    steam VARCHAR(32),
    water VARCHAR(32),
    irrigation VARCHAR(32),
    solar VARCHAR(32),
    gas VARCHAR(32),
    industry VARCHAR(255),
    subindustry VARCHAR(255),
    heatingtype VARCHAR(255),
    yearbuilt INTEGER,
    date_opened VARCHAR(64),
    numberoffloors INTEGER,
    occupants INTEGER,
    energystarscore DOUBLE PRECISION,
    eui DOUBLE PRECISION,
    site_eui DOUBLE PRECISION,
    source_eui DOUBLE PRECISION,
    leed_level VARCHAR(64),
    rating VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS weather_data (
    timestamp TIMESTAMP NOT NULL,
    site_id VARCHAR(128),
    "airTemperature" DOUBLE PRECISION,
    "cloudCoverage" DOUBLE PRECISION,
    "dewTemperature" DOUBLE PRECISION,
    "precipDepth1HR" DOUBLE PRECISION,
    "precipDepth6HR" DOUBLE PRECISION,
    "seaLvlPressure" DOUBLE PRECISION,
    "windDirection" DOUBLE PRECISION,
    "windSpeed" DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS meter_readings (
    timestamp TIMESTAMP NOT NULL,
    building_id VARCHAR(128) NOT NULL,
    meter VARCHAR(64) NOT NULL,
    meter_reading DOUBLE PRECISION
);
