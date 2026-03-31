import pandas as pd
from sqlalchemy import create_engine, text
import glob
import os
import time

# PostgreSQL 连接字符串配置
DB_USER = 'admin'
DB_PASSWORD = 'adminpassword'
DB_HOST = 'localhost'
DB_PORT = '15432'
DB_NAME = 'building_energy'

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

# 数据文件相对路径
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
METADATA_PATH = os.path.join(BASE_DIR, 'metadata', 'metadata.csv')
CLEANED_DATA = os.path.join(BASE_DIR, 'cleaned', '*_cleaned.csv')
WEATHER_PATH = os.path.join(BASE_DIR, 'weather', 'weather.csv')

def import_metadata():
    print("==== 开始导入建筑元数据 ====")
    if not os.path.exists(METADATA_PATH):
        print(f"找不到 metadata 文件: {METADATA_PATH}")
        return
        
    df_meta = pd.read_csv(METADATA_PATH)
    # 将元数据写入 Postgres 表 'building_metadata'
    df_meta.to_sql('building_metadata', engine, if_exists='replace', index=False)
    print(f"[{time.strftime('%H:%M:%S')}] 成功导入了 {len(df_meta)} 条元数据记录！\n")

def import_meter_data():
    print("==== 开始处理能耗数据 ====")
    print(f"[{time.strftime('%H:%M:%S')}] 清空旧的meter_readings表")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS meter_readings CASCADE;"))
        
    files = glob.glob(CLEANED_DATA)
    
    if not files:
        print(f"找不到任何清洗后的能耗数据文件，请检查路径: {CLEANED_DATA}")
        return
        
    for file in files:
        # 文件名形式: electricity_cleaned.csv -> 提取出 electricity
        meter_type = os.path.basename(file).split('_')[0]
        print(f"\n[{time.strftime('%H:%M:%S')}] 正在处理能耗类型: {meter_type} ({os.path.basename(file)})")
        
        start_time = time.time()
        
        # 宽表读取
        print(f"[{time.strftime('%H:%M:%S')}] 正在加载 CSV 文件到内存...")
        df = pd.read_csv(file)
        
        # 逆透视 (Melt): 把建筑ID从列名转换成行数据 
        # (来源：notebook/00_All-meters-dataset.ipynb)
        print(f"[{time.strftime('%H:%M:%S')}] 正在转换数据格式 (宽表转长表)...")
        df_long = pd.melt(df, id_vars=["timestamp"], var_name="building_id", value_name="meter_reading")
        
        # 添加仪表类型字段
        df_long["meter"] = meter_type
        
        # 时间字段格式化
        df_long["timestamp"] = pd.to_datetime(df_long["timestamp"])
        
        # 去除空值 (NaN表示因为异常或读数为0而在清洗阶段被剔除的数据，不入库以节省空间和提高效率)
        df_long = df_long.dropna(subset=['meter_reading'])
        
        # 分批写入数据库
        total_rows = len(df_long)
        print(f"[{time.strftime('%H:%M:%S')}] 准备将 {total_rows} 条有效记录写入 PostgreSQL...")
        
        # if_exists='append'表存在就追加数据，所有的能耗数据都会汇总在 `meter_readings` 一张表中
        # 为了防止内存占用过高而设chunksize批量插入参数
        df_long.to_sql('meter_readings', engine, if_exists='append', index=False, chunksize=50000)
        
        elapsed = time.time() - start_time
        print(f"[{time.strftime('%H:%M:%S')}] [完成] {meter_type} 导入耗时: {elapsed:.2f} 秒.")

def import_weather_data():
    print("==== 开始导入天气数据 ====")
    if not os.path.exists(WEATHER_PATH):
        print(f"找不到 weather 文件: {WEATHER_PATH}")
        return
        
    start_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] 正在加载天气数据到内存...")
    df_weather = pd.read_csv(WEATHER_PATH)
    
    # 格式化时间戳
    print(f"[{time.strftime('%H:%M:%S')}] 正在格式化时间戳...")
    df_weather['timestamp'] = pd.to_datetime(df_weather['timestamp'])
    
    # 写入数据库表 'weather_data'
    total_rows = len(df_weather)
    print(f"[{time.strftime('%H:%M:%S')}] 准备将 {total_rows} 条天气记录分批写入 PostgreSQL...")
    df_weather.to_sql('weather_data', engine, if_exists='replace', index=False, chunksize=50000)
    
    elapsed = time.time() - start_time
    print(f"[{time.strftime('%H:%M:%S')}] 天气数据导入完成，耗时: {elapsed:.2f} 秒！\n")

if __name__ == "__main__":
    import_metadata()
    import_weather_data()
    import_meter_data()
