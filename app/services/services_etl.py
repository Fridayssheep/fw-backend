import logging
import os
import time

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.core.database import engine
from app.core.init_db import ensure_indexes

logger = logging.getLogger(__name__)

_METADATA_FLOAT_COLUMNS = {
    "sqm",
    "sqft",
    "lat",
    "lng",
    "energystarscore",
    "eui",
    "site_eui",
    "source_eui",
}

_METADATA_INT_COLUMNS = {
    "yearbuilt",
    "numberoffloors",
    "occupants",
}

_RAW_METER_UPLOAD_CHUNK_ROWS = int(os.getenv("RAW_METER_UPLOAD_CHUNK_ROWS", "1000"))
_METADATA_UPLOAD_CHUNK_ROWS = int(os.getenv("METADATA_UPLOAD_CHUNK_ROWS", "2000"))
_WEATHER_UPLOAD_CHUNK_ROWS = int(os.getenv("WEATHER_UPLOAD_CHUNK_ROWS", "50000"))
_NON_ELECTRIC_ZERO_RUN_THRESHOLD = 24


def _ensure_indexes_after_upload(upload_type: str) -> None:
    # In incremental upload mode, tables may appear gradually.
    # Re-run index ensure after each successful import to backfill missing indexes.
    try:
        ensure_indexes()
    except Exception:
        # Do not roll back imported data if index backfill fails.
        logger.exception("Index ensure failed after %s upload.", upload_type)


def _normalize_numeric_series(series: pd.Series) -> pd.Series:
    # Metadata CSV may contain thousands separators like "1,515".
    cleaned = series.astype("string").str.replace(",", "", regex=False).str.strip()
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA})
    return pd.to_numeric(cleaned, errors="coerce")


def _normalize_csv_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed_columns: dict[str, str] = {}
    for column in df.columns:
        normalized = str(column).replace("\ufeff", "").strip()
        lowered = normalized.lower()
        if lowered == "timestamp":
            normalized = "timestamp"
        elif lowered == "site_id":
            normalized = "site_id"
        renamed_columns[column] = normalized
    return df.rename(columns=renamed_columns)


def _ensure_required_columns(df: pd.DataFrame, required_columns: set[str], upload_type: str) -> None:
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(
            f"{upload_type} CSV 缺少必需列: {', '.join(missing_columns)}。"
            f" 当前表头: {', '.join(map(str, df.columns[:10]))}"
        )


def _read_csv_chunks(file_path: str, chunk_rows: int) -> pd.io.parsers.TextFileReader:
    # utf-8-sig handles Excel/Windows generated BOM safely.
    return pd.read_csv(
        file_path,
        chunksize=chunk_rows,
        encoding="utf-8-sig",
        skipinitialspace=True,
    )


def _normalize_metadata_frame(df_meta: pd.DataFrame) -> pd.DataFrame:
    for column in _METADATA_FLOAT_COLUMNS:
        if column in df_meta.columns:
            df_meta[column] = _normalize_numeric_series(df_meta[column])

    for column in _METADATA_INT_COLUMNS:
        if column in df_meta.columns:
            numeric = _normalize_numeric_series(df_meta[column])
            df_meta[column] = numeric.round().astype("Int64")

    return df_meta


def _clean_electricity_chunk(df_chunk: pd.DataFrame) -> pd.DataFrame:
    cleaned = df_chunk.copy()
    value_columns = [column for column in cleaned.columns if column != "timestamp"]
    cleaned[value_columns] = cleaned[value_columns].replace(0, np.nan)
    return cleaned


def _clean_non_electric_chunk(df_chunk: pd.DataFrame) -> pd.DataFrame:
    cleaned = df_chunk.copy()
    value_columns = [column for column in cleaned.columns if column != "timestamp"]
    if not value_columns:
        return cleaned

    is_zero = cleaned[value_columns] == 0
    for column in value_columns:
        zero_series = is_zero[column]
        if not zero_series.any():
            continue
        zero_groups = zero_series.ne(zero_series.shift()).cumsum()
        group_sizes = zero_series.groupby(zero_groups).transform("size")
        mask = zero_series & (group_sizes > _NON_ELECTRIC_ZERO_RUN_THRESHOLD)
        cleaned.loc[mask, column] = np.nan
    return cleaned


def _flush_meter_chunk(df_chunk: pd.DataFrame, meter_type: str) -> int:
    if df_chunk.empty:
        return 0

    df_long = pd.melt(
        df_chunk,
        id_vars=["timestamp"],
        var_name="building_id",
        value_name="meter_reading",
    )
    df_long["meter"] = meter_type
    df_long = df_long.dropna(subset=["meter_reading"])
    if df_long.empty:
        return 0

    row_count = len(df_long)
    df_long.to_sql("meter_readings", engine, if_exists="append", index=False, chunksize=50000)
    return row_count


def process_metadata_upload(file_path: str) -> None:
    """Import and overwrite building metadata."""
    logger.info("Start processing metadata file: %s", file_path)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM building_metadata;"))

        inserted_rows = 0
        for chunk_index, df_meta in enumerate(
            _read_csv_chunks(file_path, _METADATA_UPLOAD_CHUNK_ROWS),
            start=1,
        ):
            normalized_chunk = _normalize_metadata_frame(_normalize_csv_columns(df_meta))
            normalized_chunk.to_sql("building_metadata", engine, if_exists="append", index=False)
            inserted_rows += len(normalized_chunk)
            logger.info(
                "[metadata] processed csv chunk %s, appended %s rows so far.",
                chunk_index,
                inserted_rows,
            )

        _ensure_indexes_after_upload("metadata")
        logger.info("Metadata import completed. appended_rows=%s", inserted_rows)
    except Exception:
        logger.exception("Metadata upload failed for file: %s", file_path)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def process_weather_upload(file_path: str) -> None:
    """Import and overwrite weather time-series data."""
    logger.info("Start processing weather file: %s", file_path)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM weather_data;"))

        inserted_rows = 0
        for chunk_index, df_weather in enumerate(
            _read_csv_chunks(file_path, _WEATHER_UPLOAD_CHUNK_ROWS),
            start=1,
        ):
            df_weather = _normalize_csv_columns(df_weather)
            _ensure_required_columns(df_weather, {"timestamp", "site_id"}, "weather")
            df_weather["timestamp"] = pd.to_datetime(df_weather["timestamp"], errors="raise")
            df_weather.to_sql("weather_data", engine, if_exists="append", index=False, chunksize=50000)
            inserted_rows += len(df_weather)
            logger.info(
                "[weather] processed csv chunk %s, appended %s rows so far.",
                chunk_index,
                inserted_rows,
            )

        _ensure_indexes_after_upload("weather")
        logger.info("Weather import completed. appended_rows=%s", inserted_rows)
    except Exception:
        logger.exception("Weather upload failed for file: %s", file_path)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def process_raw_meter_upload(meter_type: str, file_path: str) -> None:
    """Clean raw wide-meter CSV and append into normalized meter_readings."""
    logger.info("Start processing raw meter file [%s]: %s", meter_type, file_path)
    try:
        start_time = time.time()
        inserted_rows = 0
        chunk_index = 0
        pending_tail: pd.DataFrame | None = None

        reader = _read_csv_chunks(file_path, _RAW_METER_UPLOAD_CHUNK_ROWS)

        for raw_chunk in reader:
            chunk_index += 1
            raw_chunk = _normalize_csv_columns(raw_chunk)
            _ensure_required_columns(raw_chunk, {"timestamp"}, f"raw/{meter_type}")
            raw_chunk["timestamp"] = pd.to_datetime(raw_chunk["timestamp"], errors="raise")
            combined_chunk = (
                pd.concat([pending_tail, raw_chunk], ignore_index=True)
                if pending_tail is not None and not pending_tail.empty
                else raw_chunk.reset_index(drop=True)
            )

            if meter_type == "electricity":
                cleaned_chunk = _clean_electricity_chunk(combined_chunk)
                written = _flush_meter_chunk(cleaned_chunk, meter_type)
                inserted_rows += written
                pending_tail = None
            else:
                cleaned_chunk = _clean_non_electric_chunk(combined_chunk)
                if len(combined_chunk) > _NON_ELECTRIC_ZERO_RUN_THRESHOLD:
                    flush_count = len(combined_chunk) - _NON_ELECTRIC_ZERO_RUN_THRESHOLD
                    flush_chunk = cleaned_chunk.iloc[:flush_count].copy()
                    pending_tail = combined_chunk.iloc[flush_count:].reset_index(drop=True)
                else:
                    flush_chunk = cleaned_chunk.iloc[0:0].copy()
                    pending_tail = combined_chunk.reset_index(drop=True)

                written = _flush_meter_chunk(flush_chunk, meter_type)
                inserted_rows += written

            logger.info(
                "[%s] processed csv chunk %s, appended %s normalized rows so far.",
                meter_type,
                chunk_index,
                inserted_rows,
            )

        if pending_tail is not None and not pending_tail.empty:
            cleaned_tail = _clean_non_electric_chunk(pending_tail) if meter_type != "electricity" else _clean_electricity_chunk(pending_tail)
            inserted_rows += _flush_meter_chunk(cleaned_tail, meter_type)

        _ensure_indexes_after_upload(f"raw_meter:{meter_type}")

        cost = time.time() - start_time
        logger.info("[%s] meter import completed. appended_rows=%s cost=%.2fs", meter_type, inserted_rows, cost)
    except Exception:
        logger.exception("[%s] raw meter upload failed for file: %s", meter_type, file_path)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
