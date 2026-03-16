import pandas as pd
import numpy as np
import glob
import os
import time

def clean_electricity(df):
    """
    清洗电力表数据：
    将所有的 0 读数替换为 NaN 空值。
    """
    print(f"    [{time.strftime('%H:%M:%S')}] 执行规则：将 electricity表 中异常 0 读数清理为 NaN...")
    # 找到所有的建筑列（排除第一列 timestamp）
    cols = [c for c in df.columns if c != 'timestamp']
    # 批量将 0 替换为 NaN
    df[cols] = df[cols].replace(0, np.nan)
    return df

def remove_prolonged_zeros(df, max_zero_hours=24):
    """
    清洗其他表（水、气等）：
    连续超出 max_zero_hours的0读数将被认定为仪表故障或宕机。
    """
    print(f"    [{time.strftime('%H:%M:%S')}] 执行规则：将连续 {max_zero_hours} 小时以上的 0 读数清理为 NaN...")
    cols = [c for c in df.columns if c != 'timestamp']
    
    # 识别出所有等于 0 的位置
    is_zero = (df[cols] == 0)
    
    for col in cols:
        # 如果整栋大楼该类仪表没有 0 读数，跳过提高速度
        if not is_zero[col].any():
            continue
        
        # 使用 Pandas 向量化操作找到连续为 0 的块段
        s = is_zero[col]
        # 当连续状态改变时产生新 id，从而分块
        zero_groups = s.ne(s.shift()).cumsum()
        
        # 计算每个连续块的长度
        group_sizes = s.groupby(zero_groups).transform('size')
        
        # 条件：这个位置值本身是 0，且它所属的连续 0 块总长度大于 max_zero_hours
        mask = s & (group_sizes > max_zero_hours)
        
        df.loc[mask, col] = np.nan
        
    return df

def run_pipeline():
    print("====== 建筑能耗数据清洗开始 ======")
    # 数据文件相对路径
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    RAW_DIR = os.path.join(BASE_DIR, 'raw')
    CLEANED_DIR = os.path.join(BASE_DIR, 'cleaned')
    
    os.makedirs(CLEANED_DIR, exist_ok=True)
    
    # 提取所有 CSV 文件
    files = glob.glob(os.path.join(RAW_DIR, '*.csv'))
    if not files:
        print(f"[{time.strftime('%H:%M:%S')}] 错误: 在 {RAW_DIR} 下没有找到任何 raw 数据！")
        return
        
    for file in files:
        filename = os.path.basename(file)
        meter_type = filename.split('.')[0]  # 文件名去掉后缀
        
        print(f"\n[{time.strftime('%H:%M:%S')}] [开始处理传感器类型: {meter_type}]")
        start_time = time.time()
        
        df = pd.read_csv(file)
        print(f"    [{time.strftime('%H:%M:%S')}] -> 宽表加载完成。包含 {df.shape[0]} 个时间点，{df.shape[1]-1} 栋大楼的传感器数据。")
        
        # 根据传感器类型执行清洗规则流
        if meter_type == 'electricity':
            df = clean_electricity(df)
        else:
            df = remove_prolonged_zeros(df, max_zero_hours=24)
            
        # 导出清洗后的文件
        out_file = os.path.join(CLEANED_DIR, f"{meter_type}_cleaned.csv")
        df.to_csv(out_file, index=False)
        
        cost = time.time() - start_time
        print(f"    [{time.strftime('%H:%M:%S')}] -> [完成] 数据已清洗并导出至: {out_file} (总耗时: {cost:.2f} 秒)")
        
    print("\n====== 数据清洗任务执行完毕 ======")

if __name__ == "__main__":
    run_pipeline()