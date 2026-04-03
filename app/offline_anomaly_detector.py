import os
import time
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.ensemble import IsolationForest
import warnings
warnings.filterwarnings('ignore') 

DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "adminpassword")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "5432") 
DB_NAME = os.getenv("DB_NAME", "building_energy")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

def get_target_tasks(limit=5):
    """
    获取要跑批的建筑和表计组合。
    初期为了测试速度，默认只跑前 5 个组合。实际全线上线时去掉 LIMIT。
    """
    with engine.connect() as conn:
        print(f"[{time.strftime('%H:%M:%S')}] 正在获取待处理的建筑表计任务列表...")
        query = f"SELECT DISTINCT building_id, meter FROM meter_readings ORDER BY building_id LIMIT {limit}"
        result = conn.execute(text(query))
        return [(row[0], row[1]) for row in result]

def detect_anomalies_for_series(building_id, meter):
    """处理单个建筑的单个传感器数据序列，挖掘异常事件"""
    print(f"\n[{time.strftime('%H:%M:%S')}] 开始分析: 建筑 [{building_id}] | 表计 [{meter}]")
    
    # 1. 加载数据
    query = """
        SELECT timestamp, meter_reading 
        FROM meter_readings 
        WHERE building_id = %(b_id)s AND meter = %(m_type)s
        ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, engine, params={"b_id": building_id, "m_type": meter})
    
    if df.empty or len(df) < 100:
        print("  -> 数据量过少，跳过检测")
        return []
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    events_to_insert = []
    
    # ==========================================
    # 算法 1: 断流/数据缺失异常 (Missing Data)
    # 规则: 间隔超过 4 小时判定为断流异常
    # ==========================================
    df['time_diff'] = df['timestamp'].diff().dt.total_seconds() / 3600.0
    missing_mask = df['time_diff'] > 4.0
    for idx, row in df[missing_mask].iterrows():
        # 断流的开始时间是上一条记录的时间，结束时间是当前恢复记录的时间
        prev_time = df.loc[idx - 1, 'timestamp']
        events_to_insert.append({
            'building_id': building_id, 'site_id': None, 'meter': meter,
            'start_time': prev_time, 'end_time': row['timestamp'],
            'peak_deviation': float(row['time_diff']), # 记录断流时长
            'severity': 'HIGH',
            'detected_by': 'missing_data_detector',
            'description': f"表计断流/数据缺失长达 {row['time_diff']:.1f} 小时"
        })

    # ==========================================
    # 算法 2: Z-Score 突发极值检测 (Point Anomalies)
    # 规则: 偏离均值 3 个标准差以上
    # ==========================================
    mean_val = df['meter_reading'].mean()
    std_val = df['meter_reading'].std()
    
    if std_val > 0: # 防止标准差为 0 导致除以 0
        df['z_score'] = np.abs((df['meter_reading'] - mean_val) / std_val)
        z_mask = df['z_score'] > 3.0
        
        for idx, row in df[z_mask].iterrows():
            events_to_insert.append({
                'building_id': building_id, 'site_id': None, 'meter': meter,
                'start_time': row['timestamp'], 'end_time': row['timestamp'],
                'peak_deviation': float(row['z_score']),
                'severity': 'HIGH' if row['z_score'] > 5.0 else 'MEDIUM',
                'detected_by': 'z_score_detector',
                'description': f"发生突发性数值读数异常，Z-Score偏离度高达 {row['z_score']:.2f}"
            })

    # ==========================================
    # 算法 3: Isolation Forest 孤立森林 (Contextual Anomalies)
    # 规则: 提取时间特征(小时间、星期天)，发现“不符合该时间段规律”的隐蔽异常
    # ==========================================
    # 提取时间特征
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    
    # 准备特征矩阵
    features = df[['meter_reading', 'hour', 'day_of_week']].fillna(0)
    
    # 假设建筑一年内大约只有 0.5% 的时间存在这种隐性异常
    iso_forest = IsolationForest(contamination=0.005, random_state=42)
    df['iso_label'] = iso_forest.fit_predict(features) # -1 为异常, 1 为正常
    
    iso_mask = df['iso_label'] == -1
    for idx, row in df[iso_mask].iterrows():
        # 如果这个点刚才已经被 Z-Score 报出来了，就不重复报了
        if row.get('z_score', 0) > 3.0:
            continue
            
        events_to_insert.append({
            'building_id': building_id, 'site_id': None, 'meter': meter,
            'start_time': row['timestamp'], 'end_time': row['timestamp'],
            'peak_deviation': None, # 孤立森林的分数比较难直接对标量化，这里存 None
            'severity': 'MEDIUM',
            'detected_by': 'isolation_forest',
            'description': f"周期性特征离群异常，读数 {row['meter_reading']:.2f} 不符合该时间段({row['hour']}点, 星期{row['day_of_week']})的历史规律"
        })

    # 4. 批量写入数据库
    if events_to_insert:
        print(f"  -> 共检出 {len(events_to_insert)} 条异常事件，准备写入数据库...")
        df_events = pd.DataFrame(events_to_insert)
        df_events.to_sql('anomaly_events', engine, if_exists='append', index=False)
        print(f"  -> 写入完成！")
    else:
        print("  -> 健康状态良好，未检出明显的长期异常。")
        
    return events_to_insert

def run_batch_pipeline():
    print("====== 启动能耗数据历史跑批诊断管道 (Batch Pipeline) ======")
    start_time = time.time()
    
    # 拿到所有的任务组合
    tasks = get_target_tasks(limit=3) # 测试时只跑前 3 个建筑-表计组合
    
    total_events = 0
    for building_id, meter in tasks:
        events = detect_anomalies_for_series(building_id, meter)
        total_events += len(events)
        
    print(f"\n====== 管道执行完毕，总计发现并记录了 {total_events} 条异常事件！(耗时 {time.time() - start_time:.2f}s) ======")

if __name__ == "__main__":
    run_batch_pipeline()
