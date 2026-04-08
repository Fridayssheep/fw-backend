import logging
import os
import time

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.core.database import engine
from app.core.init_db import ensure_indexes

logger = logging.getLogger(__name__)


def _ensure_indexes_after_upload(upload_type: str) -> None:
    # In incremental upload mode, tables may appear gradually.
    # Re-run index ensure after each successful import to backfill missing indexes.
    try:
        ensure_indexes()
    except Exception:
        # Do not roll back imported data if index backfill fails.
        logger.exception("Index ensure failed after %s upload.", upload_type)


def process_metadata_upload(file_path: str) -> None:
    """Import and overwrite building metadata."""
    logger.info("Start processing metadata file: %s", file_path)
    try:
        df_meta = pd.read_csv(file_path)

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM building_metadata;"))

        logger.info("Writing %s metadata rows...", len(df_meta))
        df_meta.to_sql("building_metadata", engine, if_exists="append", index=False)
        _ensure_indexes_after_upload("metadata")
        logger.info("Metadata import completed.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def process_weather_upload(file_path: str) -> None:
    """Import and overwrite weather time-series data."""
    logger.info("Start processing weather file: %s", file_path)
    try:
        df_weather = pd.read_csv(file_path)
        df_weather["timestamp"] = pd.to_datetime(df_weather["timestamp"])

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM weather_data;"))

        logger.info("Writing %s weather rows...", len(df_weather))
        df_weather.to_sql("weather_data", engine, if_exists="append", index=False, chunksize=50000)
        _ensure_indexes_after_upload("weather")
        logger.info("Weather import completed.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def process_raw_meter_upload(meter_type: str, file_path: str) -> None:
    """Clean raw wide-meter CSV and append into normalized meter_readings."""
    logger.info("Start processing raw meter file [%s]: %s", meter_type, file_path)
    try:
        start_time = time.time()

        df = pd.read_csv(file_path)

        if meter_type == "electricity":
            cols = [c for c in df.columns if c != "timestamp"]
            df[cols] = df[cols].replace(0, np.nan)
        else:
            cols = [c for c in df.columns if c != "timestamp"]
            is_zero = (df[cols] == 0)
            for col in cols:
                if not is_zero[col].any():
                    continue
                s = is_zero[col]
                zero_groups = s.ne(s.shift()).cumsum()
                group_sizes = s.groupby(zero_groups).transform("size")
                mask = s & (group_sizes > 24)
                df.loc[mask, col] = np.nan

        df_long = pd.melt(df, id_vars=["timestamp"], var_name="building_id", value_name="meter_reading")
        df_long["meter"] = meter_type
        df_long["timestamp"] = pd.to_datetime(df_long["timestamp"])
        df_long = df_long.dropna(subset=["meter_reading"])

        total_rows = len(df_long)
        logger.info("Clean completed. Appending %s rows into meter_readings...", total_rows)
        df_long.to_sql("meter_readings", engine, if_exists="append", index=False, chunksize=50000)
        _ensure_indexes_after_upload(f"raw_meter:{meter_type}")

        cost = time.time() - start_time
        logger.info("[%s] meter import completed. cost=%.2fs", meter_type, cost)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
