import os  # 导入读取环境变量所需的标准库。
from collections.abc import Sequence  # 导入序列类型注解，方便给参数标注类型。
from typing import Any  # 导入任意类型注解，方便描述通用参数。

from sqlalchemy import create_engine  # 导入 SQLAlchemy 的引擎创建函数。
from sqlalchemy import text  # 导入 SQL 文本函数，方便直接执行原生 SQL。
from sqlalchemy.engine import Engine  # 导入引擎类型，方便做类型标注。


DB_HOST = os.getenv("DB_HOST", "127.0.0.1")  # 读取数据库主机地址，默认使用本机映射地址。
DB_PORT = os.getenv("DB_PORT", "5432")  # 读取数据库端口，默认使用项目容器映射端口。
DB_NAME = os.getenv("DB_NAME", "building_energy")  # 读取数据库名，默认使用当前项目数据库。
DB_USER = os.getenv("DB_USER", "admin")  # 读取数据库用户名，默认使用项目初始化账号。
DB_PASSWORD = os.getenv("DB_PASSWORD", "adminpassword")  # 读取数据库密码，默认使用项目初始化密码。


DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"  # 拼接 SQLAlchemy 连接串。


engine: Engine = create_engine(  # 创建同步数据库引擎，当前项目用同步方式最简单直接。
    DATABASE_URL,  # 使用上面拼好的数据库连接串。
    pool_pre_ping=True,  # 每次取连接前先做探活，避免长时间空闲连接失效。
)


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:  # 定义查询多行数据的通用函数。
    with engine.connect() as connection:  # 打开一个数据库连接。
        result = connection.execute(text(sql), params or {})  # 执行带参数的原生 SQL。
        return [dict(row) for row in result.mappings().all()]  # 把结果转成字典列表返回，方便后续直接组装响应。


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:  # 定义查询单行数据的通用函数。
    with engine.connect() as connection:  # 打开一个数据库连接。
        result = connection.execute(text(sql), params or {})  # 执行带参数的原生 SQL。
        row = result.mappings().first()  # 只取第一行结果。
        return dict(row) if row else None  # 如果查到数据就转成字典，否则返回空。


def fetch_scalar(sql: str, params: dict[str, Any] | None = None) -> Any:  # 定义查询单个标量值的通用函数。
    with engine.connect() as connection:  # 打开一个数据库连接。
        result = connection.execute(text(sql), params or {})  # 执行带参数的原生 SQL。
        return result.scalar()  # 直接返回第一行第一列的值。


def execute_sql(sql: str, params: dict[str, Any] | None = None) -> None:  # 定义执行写操作的通用函数。
    with engine.begin() as connection:  # 使用事务方式执行 SQL，保证写操作完整提交。
        connection.execute(text(sql), params or {})  # 执行带参数的原生 SQL。


def build_in_clause(  # 定义构造 IN 子句的工具函数。
    field_name: str,  # 接收字段名，例如 mr.building_id。
    values: Sequence[str],  # 接收要放进 IN 条件里的值列表。
    prefix: str,  # 接收参数名前缀，避免多个条件时重名。
) -> tuple[str, dict[str, Any]]:  # 返回 SQL 片段和对应参数字典。
    placeholders: list[str] = []  # 准备存放形如 :building_id_0 的占位符列表。
    params: dict[str, Any] = {}  # 准备存放实际参数值。
    for index, value in enumerate(values):  # 遍历所有需要拼接的值。
        key = f"{prefix}_{index}"  # 为每个值生成唯一参数名。
        placeholders.append(f":{key}")  # 把参数占位符放进列表。
        params[key] = value  # 把实际值写入参数字典。
    clause = f"{field_name} IN ({', '.join(placeholders)})"  # 拼出最终的 IN 条件片段。
    return clause, params  # 把 SQL 片段和参数字典一起返回。
