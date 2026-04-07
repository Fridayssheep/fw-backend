import asyncio
import json

_MAIN_LOOP = None

def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """保存 FastAPI 主事件循环，用于跨线程将同步代码的消息推入异步队列。"""
    global _MAIN_LOOP
    _MAIN_LOOP = loop

class StreamBroker:
    def __init__(self) -> None:
        self.clients: set[asyncio.Queue] = set()
        
    def add_client(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self.clients.add(q)
        return q
        
    def remove_client(self, q: asyncio.Queue) -> None:
        if q in self.clients:
            self.clients.remove(q)
            
    def publish_sync(self, message: str, context: str = "") -> None:
        """从同步线程（如 MCP 各种 tool 中）发起状态广播。"""
        global _MAIN_LOOP
        if not _MAIN_LOOP:
            return
            
        data = json.dumps({"action": "mcp_tool", "message": message, "context": context}, ensure_ascii=False)
        
        def _put() -> None:
            for q in list(self.clients):
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    pass
                    
        # 安全地将同步调用穿透回主线程事件循环
        _MAIN_LOOP.call_soon_threadsafe(_put)

# 全局唯一消息代理
broker = StreamBroker()
