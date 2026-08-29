import logging
from typing import Optional
import httpx

logger = logging.getLogger("app.core.http_client")


class HttpClientManager:
    """
    Singleton HTTP Client Manager with high-performance Keep-Alive Connection Pool:
    - max_keepalive_connections: 20 (keeps TCP/TLS handshakes warm for 9Router, Telegram, Meta)
    - max_connections: 100 concurrent sockets
    - keepalive_expiry: 120.0 seconds
    """
    _instance: Optional["HttpClientManager"] = None
    _client: Optional[httpx.AsyncClient] = None

    def __new__(cls) -> "HttpClientManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=120.0,
            )
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
                limits=limits,
                follow_redirects=True,
            )
            logger.info("[HTTP-Client] Shared Singleton AsyncClient initialized")
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            logger.info("[HTTP-Client] Closing Shared AsyncClient...")
            await self._client.aclose()
            self._client = None
            logger.info("[HTTP-Client] Shared AsyncClient closed cleanly")


http_client_manager = HttpClientManager()
