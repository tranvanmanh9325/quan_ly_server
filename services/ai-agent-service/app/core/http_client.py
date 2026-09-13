import logging
from typing import Optional
import httpx

logger = logging.getLogger("app.core.http_client")


class HttpClientManager:
    """
    Singleton HTTP Connection Pool Manager:
    - Shared API Client: Keep-Alive pool for LLM (Groq, OpenRouter) & Telegram API.
    - Media Downloader Client: IPv4 bound, streaming-optimized client with dedicated socket limits.
    """
    _instance: Optional["HttpClientManager"] = None
    _client: Optional[httpx.AsyncClient] = None
    _media_client: Optional[httpx.AsyncClient] = None

    def __new__(cls) -> "HttpClientManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_client(self) -> httpx.AsyncClient:
        """Returns shared Keep-Alive client for REST APIs & LLM streams."""
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

    def get_media_client(self) -> httpx.AsyncClient:
        """
        Returns persistent connection pool for Media Downloader (TikWM, Facebook redirects).
        Binds to IPv4 (0.0.0.0) to eliminate Docker bridge Errno 101 unreachable network errors.
        """
        if self._media_client is None or self._media_client.is_closed:
            transport = httpx.AsyncHTTPTransport(
                local_address="0.0.0.0",
                retries=2,
            )
            limits = httpx.Limits(
                max_keepalive_connections=10,
                max_connections=30,
                keepalive_expiry=60.0,
            )
            self._media_client = httpx.AsyncClient(
                transport=transport,
                limits=limits,
                timeout=httpx.Timeout(connect=10.0, read=45.0, write=30.0, pool=10.0),
                follow_redirects=True,
                max_redirects=5,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                    )
                },
            )
            logger.info("[HTTP-Client] Persistent Media AsyncClient initialized")
        return self._media_client

    async def close(self) -> None:
        """Clean shutdown of all pooled connection sockets."""
        if self._client is not None and not self._client.is_closed:
            logger.info("[HTTP-Client] Closing Shared AsyncClient...")
            await self._client.aclose()
            self._client = None
        if self._media_client is not None and not self._media_client.is_closed:
            logger.info("[HTTP-Client] Closing Media AsyncClient...")
            await self._media_client.aclose()
            self._media_client = None
        logger.info("[HTTP-Client] All HTTP connection pools closed cleanly")


http_client_manager = HttpClientManager()
