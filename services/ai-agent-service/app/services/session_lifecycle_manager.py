"""
Session Lifecycle Manager (Phase 4 Remediation).
Guarantees clean session lifecycle, remote GPU termination, and resource cleanup
in invariant finally blocks.
"""

import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class JobSessionRecord:
    """Tracking record for active resources associated with a specific job."""
    job_id: str
    active_providers: List[str] = field(default_factory=list)
    temp_files: List[Path] = field(default_factory=list)
    temp_dirs: List[Path] = field(default_factory=list)
    protected_deliverables: List[Path] = field(default_factory=list)
    remote_asset_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class RemoteSessionRegistry:
    """
    Thread-safe Central Session Registry for all remote GPU resources & temporary disk assets.
    Ensures zero resource leaks even during unhandled exceptions or cancellations.
    """

    def __init__(self):
        self._sessions: Dict[str, JobSessionRecord] = {}
        self._lock = threading.Lock()

    def get_or_create(self, job_id: str) -> JobSessionRecord:
        """Retrieve existing record or initialize a new JobSessionRecord for job_id."""
        with self._lock:
            if job_id not in self._sessions:
                self._sessions[job_id] = JobSessionRecord(job_id=job_id)
            return self._sessions[job_id]

    def register_deliverable_path(self, job_id: str, path: Union[str, Path]) -> None:
        """
        Register a protected deliverable target file that must NEVER be deleted during cleanup.
        Any attempt to register or unlink this path as temporary scratch will be rejected.
        """
        if not path:
            return
        p = Path(path).resolve()
        rec = self.get_or_create(job_id)
        with self._lock:
            if p not in rec.protected_deliverables:
                rec.protected_deliverables.append(p)
            # Purge from temp_files if accidentally registered previously
            rec.temp_files = [tf for tf in rec.temp_files if tf.resolve() != p]
            # Purge from temp_dirs if any temp_dir contains the deliverable
            safe_dirs = []
            for td in rec.temp_dirs:
                try:
                    if p.is_relative_to(td.resolve()):
                        logger.warning(
                            "[RemoteSessionRegistry] Removing temp_dir %s from cleanup because it contains protected deliverable %s",
                            td, p
                        )
                        continue
                except (ValueError, TypeError, AttributeError):
                    pass
                safe_dirs.append(td)
            rec.temp_dirs = safe_dirs

    def register_temp_path(self, job_id: str, path: Union[str, Path], is_dir: bool = False) -> None:
        """
        Register a temporary scratch file or directory to be deleted on session termination.
        Enforces strict safety checks: rejects any path registered as a protected deliverable.
        """
        if not path:
            return
        p = Path(path).resolve()
        rec = self.get_or_create(job_id)
        with self._lock:
            # SAFETY GUARD: Never register a deliverable target as a temporary scratch asset
            for d in rec.protected_deliverables:
                resolved_d = d.resolve()
                if p == resolved_d:
                    logger.warning(
                        "[RemoteSessionRegistry] SAFETY REJECTION: Refusing to register protected deliverable %s as temporary scratch file",
                        p
                    )
                    return
                if is_dir:
                    try:
                        if resolved_d.is_relative_to(p):
                            logger.warning(
                                "[RemoteSessionRegistry] SAFETY REJECTION: Refusing to register directory %s containing protected deliverable %s as temporary scratch dir",
                                p, resolved_d
                            )
                            return
                    except (ValueError, TypeError, AttributeError):
                        pass

            if is_dir:
                if p not in rec.temp_dirs:
                    rec.temp_dirs.append(p)
            else:
                if p not in rec.temp_files:
                    rec.temp_files.append(p)

    async def terminate_session_async(self, job_id: str) -> bool:
        """
        Guaranteed asynchronous cleanup of remote GPU sessions and temporary assets.
        Called unconditionally in finally blocks.
        """
        with self._lock:
            rec = self._sessions.pop(job_id, None)

        if not rec:
            return True

        logger.info("[RemoteSessionRegistry] Terminating session resources for job_id=%s", job_id)

        # 1. Terminate remote cloud sessions and release provider connections
        try:
            from app.services.remote_gpu_worker_client import get_remote_gpu_worker_client
            remote_client = get_remote_gpu_worker_client()
            await remote_client.terminate_all_sessions()
        except Exception as err:
            logger.warning("[RemoteSessionRegistry] Remote client termination warning: %s", err)

        # 2. Clean up temporary directories (chunk dirs, mask caches)
        for tdir in rec.temp_dirs:
            try:
                resolved_tdir = tdir.resolve()
                # Safety check: do not delete directory if it contains a protected deliverable
                is_safe = True
                for d in rec.protected_deliverables:
                    resolved_d = d.resolve()
                    if resolved_d == resolved_tdir:
                        is_safe = False
                        break
                    try:
                        if resolved_d.is_relative_to(resolved_tdir):
                            is_safe = False
                            break
                    except (ValueError, TypeError, AttributeError):
                        pass
                if not is_safe:
                    logger.warning(
                        "[RemoteSessionRegistry] SAFETY GUARD: Skipping temp dir %s containing protected deliverable",
                        tdir
                    )
                    continue
                if tdir.exists():
                    shutil.rmtree(tdir, ignore_errors=True)
            except Exception as err:
                logger.debug("[RemoteSessionRegistry] Failed deleting temp dir %s: %s", tdir, err)

        # 3. Clean up individual temporary files (excluding protected deliverables)
        protected_set = {d.resolve() for d in rec.protected_deliverables}
        for tfile in rec.temp_files:
            try:
                resolved_tfile = tfile.resolve()
                if resolved_tfile in protected_set:
                    logger.warning(
                        "[RemoteSessionRegistry] SAFETY GUARD TRIGGERED: Refusing to unlink protected deliverable %s",
                        tfile
                    )
                    continue
                if tfile.exists():
                    tfile.unlink(missing_ok=True)
            except Exception as err:
                logger.debug("[RemoteSessionRegistry] Failed unlinking temp file %s: %s", tfile, err)

        # 4. Trigger OS memory reclamation
        try:
            from app.core.memory_reclaimer import _sync_collect_and_trim
            _sync_collect_and_trim()
        except Exception:
            pass

        return True

    def terminate_session_sync(self, job_id: str) -> bool:
        """
        Synchronous thread-safe wrapper for cleanup in non-async contexts or destructors.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(asyncio.run, self.terminate_session_async(job_id)).result()
            else:
                return loop.run_until_complete(self.terminate_session_async(job_id))
        except Exception:
            return asyncio.run(self.terminate_session_async(job_id))


_global_registry_instance: Optional[RemoteSessionRegistry] = None


def get_session_registry() -> RemoteSessionRegistry:
    """Return the global singleton instance of RemoteSessionRegistry."""
    global _global_registry_instance
    if _global_registry_instance is None:
        _global_registry_instance = RemoteSessionRegistry()
    return _global_registry_instance


class GuaranteedSessionScope:
    """
    Context manager guaranteeing session and asset cleanup in finally block.
    Supports both `async with` and synchronous `with` statements.
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.registry = get_session_registry()

    async def __aenter__(self):
        self.registry.get_or_create(self.job_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            await self.registry.terminate_session_async(self.job_id)
        except Exception as exc:
            logger.error("[GuaranteedSessionScope] Cleanup exception for job %s: %s", self.job_id, exc)

    def __enter__(self):
        self.registry.get_or_create(self.job_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.registry.terminate_session_sync(self.job_id)
        except Exception as exc:
            logger.error("[GuaranteedSessionScope] Sync cleanup exception for job %s: %s", self.job_id, exc)
