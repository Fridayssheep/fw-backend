import psycopg2
import time

# 数据库连接配置
DB_USER = 'admin'
DB_PASSWORD = 'adminpassword'
DB_HOST = 'localhost'
DB_PORT = '5432'
DB_NAME = 'building_energy'

def create_indexes():
    print("==== 开始为 PostgreSQL 数据库创建索引 ====")
    
    # 使用 psycopg2 直接连接，以支持执行无法在事务中运行的扩展创建命令
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    conn.autocommit = True
    cursor = conn.cursor()

    index_queries = [
        # 1. 组合索引：针对最常见的查询 (某栋建筑的某种表在某个时间段的数据)
        ("idx_meters_building_meter_time", 
         "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_meters_building_meter_time ON meter_readings (building_id, meter, timestamp);"),
        
        # 2. 单独的时间索引：针对全系统某个时段的总耗能查询
        ("idx_meters_time", 
         "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_meters_time ON meter_readings (timestamp);"),
         
        # 3. 元数据主键索引
        ("idx_metadata_building_id",
         "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_metadata_building_id ON building_metadata (building_id);")
    ]

    for index_name, query in index_queries:
        start_time = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] 正在创建索引: {index_name} ...")
        try:
            cursor.execute(query)
            elapsed = time.time() - start_time
            print(f"  -> 成功! 耗时: {elapsed:.2f} 秒")
        except Exception as e:
            print(f"  -> 创建失败: {e}")

    cursor.close()
    conn.close()
    print("==== 索引创建完毕 ====")

if __name__ == "__main__":
    create_indexes()
