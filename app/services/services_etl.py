import logging
import os
import shutil
import time

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)


def process_metadata_upload(file_path: str) -> None:
    """处理并导入建筑基础元数据。"""
    logger.info(f"开始处理元数据文件: {file_path}")
    try:
        df_meta = pd.read_csv(file_path)
        
        with engine.begin() as conn:
            # 安全清空旧数据而不破坏表结构和索引
            conn.execute(text("DELETE FROM building_metadata;"))
            
        # 覆写导入新数据
        logger.info(f"写入 {len(df_meta)} 条元数据...")
        df_meta.to_sql("building_metadata", engine, if_exists="append", index=False)
        logger.info("元数据导入完成！")
        
    finally:
        # 清理临时文件
        if os.path.exists(file_path):
            os.remove(file_path)


def process_weather_upload(file_path: str) -> None:
    """处理并导入天气时序数据。"""
    logger.info(f"开始处理天气文件: {file_path}")
    try:
        df_weather = pd.read_csv(file_path)
        df_weather["timestamp"] = pd.to_datetime(df_weather["timestamp"])
        
        with engine.begin() as conn:
            # 安全清空旧天气数据而不破坏表结构
            conn.execute(text("DELETE FROM weather_data;"))
            
        logger.info(f"写入 {len(df_weather)} 条气象数据记录...")
        df_weather.to_sql("weather_data", engine, if_exists="append", index=False, chunksize=50000)
        logger.info("气象数据导入完成！")
        
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def process_raw_meter_upload(meter_type: str, file_path: str) -> None:
    """处理并洗清原始能耗宽表文件，追加为系统标准垂直表并触发分析。"""
    logger.info(f"开始处理并清洗 [{meter_type}] 表计流文件: {file_path}")
    try:
        start_time = time.time()
        
        # 1. 加载宽表
        df = pd.read_csv(file_path)
        
        # 2. 清洗逻辑
        if meter_type == "electricity":
            # 过滤异常的0读数
            cols = [c for c in df.columns if c != "timestamp"]
            df[cols] = df[cols].replace(0, np.nan)
        else:
            # 清理连续严重断流（比如水表气表卡死）
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

        # 3. 宽表透视解构为时序行项
        df_long = pd.melt(df, id_vars=["timestamp"], var_name="building_id", value_name="meter_reading")
        df_long["meter"] = meter_type
        df_long["timestamp"] = pd.to_datetime(df_long["timestamp"])
        
        # 剔除空项以保证数据库空间性能
        df_long = df_long.dropna(subset=["meter_reading"])
        
        # 4. 追加落库 (保留原有业务数据)
        total_rows = len(df_long)
        logger.info(f"清洗完成。准备追加写入 {total_rows} 条记录至表计读数库...")
        df_long.to_sql("meter_readings", engine, if_exists="append", index=False, chunksize=50000)
        
        cost = time.time() - start_time
        logger.info(f"[{meter_type}] 表计入库全部完成: 耗时: {cost:.2f} s")
        
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
