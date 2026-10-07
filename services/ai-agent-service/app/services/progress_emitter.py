import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class PipelineProgressEmitter:
    """
    Thread-Safe Progress Emitter bridging synchronous worker threads
    and asynchronous Telegram Bot event loops.
    
    Fixes the PEP 3156 issue where calling `asyncio.get_running_loop()` inside
    an `asyncio.to_thread` worker thread raises `RuntimeError: no running event loop`.
    """

    def __init__(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        callback: Optional[Callable[..., Any]] = None,
    ):
        if loop is not None:
            self.loop = loop
        else:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    self.loop = asyncio.get_event_loop()
                except RuntimeError:
                    self.loop = None
        self.callback = callback

    def emit(self, percent: int, stage_text: str, extra_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Dispatches progress updates thread-safely to the caller callback.
        Adapts transparently to both 2-argument (pct, text) and 3-argument (pct, text, meta) callbacks.
        """
        if not self.callback:
            return

        try:
            if self.loop and self.loop.is_running():
                if asyncio.iscoroutinefunction(self.callback):
                    # Check argument count for async callback
                    try:
                        sig = inspect.signature(self.callback)
                        param_count = len(sig.parameters)
                    except Exception:
                        param_count = 2

                    if param_count >= 3:
                        coro = self.callback(percent, stage_text, extra_data)
                    else:
                        coro = self.callback(percent, stage_text)

                    asyncio.run_coroutine_threadsafe(coro, self.loop)
                else:
                    # Sync callback invocation on event loop thread
                    try:
                        sig = inspect.signature(self.callback)
                        param_count = len(sig.parameters)
                    except Exception:
                        param_count = 2

                    if param_count >= 3:
                        self.loop.call_soon_threadsafe(self.callback, percent, stage_text, extra_data)
                    else:
                        self.loop.call_soon_threadsafe(self.callback, percent, stage_text)
            else:
                # Direct invocation fallback if event loop is not available
                try:
                    self.callback(percent, stage_text, extra_data)
                except TypeError:
                    self.callback(percent, stage_text)
        except Exception as err:
            logger.debug("[PipelineProgressEmitter] Failed to emit progress (%d%%): %s", percent, err)
