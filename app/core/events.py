import asyncio
import json
from typing import Optional

_MAIN_LOOP = None

def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """保存 FastAPI 主事件循环，用于跨线程将同步代码的消息推入异步队列。"""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


class _Client:
    """内部客户端包装：一个队列 + 可选的 topic 过滤器"""
    __slots__ = ("queue", "topics")

    def __init__(self, queue: asyncio.Queue, topics: Optional[set[str]] = None):
        self.queue = queue
        # topics=None 表示订阅全部；topics={'anomaly_detect_progress', ...} 表示只订阅指定事件
        self.topics = topics


class StreamBroker:
    def __init__(self) -> None:
        self._clients: list[_Client] = []

    def add_client(self, topics: Optional[set[str]] = None) -> asyncio.Queue:
        """
        注册 SSE 客户端。
        
        Args:
            topics: 可选订阅过滤集合。为 None 时接收所有事件；
                    否则只接收 event_type 在 topics 中的消息。
                    
        Returns:
            asyncio.Queue 供 SSE 端点消费。
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients.append(_Client(q, topics))
        return q

    def remove_client(self, q: asyncio.Queue) -> None:
        self._clients = [c for c in self._clients if c.queue is not q]

    def publish_sync(self, message: str, context: str = "", event_type: str = "mcp_tool") -> None:
        """从同步线程发起状态广播，只推送给订阅了该 event_type 的客户端。"""
        global _MAIN_LOOP
        if not _MAIN_LOOP:
            return

        data = json.dumps({"action": event_type, "message": message, "context": context}, ensure_ascii=False)

        def _put() -> None:
            for client in list(self._clients):
                # topic 过滤：如果客户端设置了 topics 且当前事件不在其中，则跳过
                if client.topics is not None and event_type not in client.topics:
                    continue
                try:
                    client.queue.put_nowait(data)
                except asyncio.QueueFull:
                    pass

        _MAIN_LOOP.call_soon_threadsafe(_put)


# 全局唯一消息代理
broker = StreamBroker()
