import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import settings
from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache
from app.services.facebook_service import FacebookService
from app.services.tiktok_service import TikTokService
from app.services.appointment_service import AppointmentService
from app.services.ai_agent import AiAgentService
from app.services.browser_agent import BrowserAgentService
from app.services.memory_service import AgentMemoryService
from app.services.telegram_bot import TelegramBot
from app.routers import health, facebook, tiktok, openai_gateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai-agent-service")


async def facebook_periodic_scan_loop(fb_service: FacebookService):
    """Background task to periodically run Facebook scan cycles."""
    logger.info("[FB-Scheduler] Started periodic scanner loop.")
    while True:
        try:
            from app.services.vnc_manager import vnc_manager
            # If user is actively using the live VNC session, pause background scan to prevent lock contention
            if vnc_manager.is_running():
                logger.debug("[FB-Scheduler] Live VNC session active; skipping scheduled scan cycle.")
                await asyncio.sleep(20)
                continue

            cfg = await fb_service.get_config_from_db()
            interval_min = max(3, cfg.get("scan_interval_minutes", 3))
            if cfg.get("enabled", False):
                logger.info("[FB-Scheduler] Running scheduled scan cycle...")
                await fb_service.run_scan_cycle()

            await asyncio.sleep(interval_min * 60)
        except asyncio.CancelledError:
            logger.info("[FB-Scheduler] Scanner loop cancelled.")
            break
        except Exception as e:
            logger.error("[FB-Scheduler] Unexpected error in scanner loop: %s", e)
            await asyncio.sleep(60)


async def tiktok_periodic_scan_loop(tt_service: TikTokService):
    """Background task to periodically run TikTok DM auto-reply and daily streak keeper checks."""
    logger.info("[TikTok-Scheduler] Started periodic scanner & streak keeper loop.")
    while True:
        try:
            from app.services.vnc_manager import vnc_manager
            if vnc_manager.is_running():
                logger.debug("[TikTok-Scheduler] Live VNC session active; skipping scheduled scan cycle.")
                await asyncio.sleep(20)
                continue

            cfg = await tt_service.get_config_from_db()
            interval_min = max(3, cfg.get("scan_interval_minutes", 3))

            # 1. Run DM scan if enabled
            if cfg.get("enabled", False):
                await tt_service.run_scan_cycle()

            # 2. Check and run daily streak keeper cycle if scheduled
            if cfg.get("streak_enabled", True):
                await tt_service.run_streak_keeper_cycle(force=False)

            await asyncio.sleep(interval_min * 60)
        except asyncio.CancelledError:
            logger.info("[TikTok-Scheduler] Scanner loop cancelled.")
            break
        except Exception as e:
            logger.error("[TikTok-Scheduler] Unexpected error in scanner loop: %s", e)
            await asyncio.sleep(60)


async def appointment_reminder_loop(appointment_service: AppointmentService, telegram_bot: TelegramBot):
    """Background task to periodically dispatch 1-hour appointment reminders."""
    logger.info("[Reminder-Scheduler] Started 1-hour appointment reminder dispatcher loop.")
    while True:
        try:
            count = await appointment_service.check_and_dispatch_reminders(telegram_bot)
            if count > 0:
                logger.info("[Reminder-Scheduler] Dispatched %d proactive appointment reminder(s).", count)
        except asyncio.CancelledError:
            logger.info("[Reminder-Scheduler] Reminder loop cancelled.")
            break
        except Exception as e:
            logger.error("[Reminder-Scheduler] Error in appointment reminder loop: %s", e)

        await asyncio.sleep(60)


async def rtk_stats_persist_loop(llm_router: LlmRouter):
    """Background task: persists RTK compression stats to DB every 30 seconds.

    Only writes when there is a pending delta (skips no-op round-trips).
    On failure, the delta is returned to the pending buffer so it retries next cycle.
    """
    logger.info("[RTK-Persist] Started RTK stats persistence loop (interval: 30s).")
    while True:
        try:
            await asyncio.sleep(30)
            await llm_router.save_stats_to_db()
        except asyncio.CancelledError:
            logger.info("[RTK-Persist] Persistence loop cancelled.")
            break
        except Exception as e:
            logger.error("[RTK-Persist] Unexpected error in persist loop: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up AI Agent & 9Router Service (Python)...")

    # 1. Initialize core 9Router Engine & Infrastructure
    llm_router = LlmRouter()
    ssh_client = SshClient()
    message_cache = FacebookMessageCache()

    # Load persisted RTK stats from DB so the counter survives container restarts
    await llm_router.load_stats_from_db()

    # 2. Initialize domain services with bidirectional wiring
    appointment_service = AppointmentService(llm_router)
    fb_service = FacebookService(message_cache, appointment_service=appointment_service)
    tiktok_service = TikTokService(llm_router=llm_router)
    browser_agent = BrowserAgentService(fb_service=fb_service)
    ai_agent = AiAgentService(llm_router, ssh_client, message_cache, fb_service)
    ai_agent.set_appointment_service(appointment_service)
    ai_agent.set_browser_agent(browser_agent)
    fb_service.set_ai_agent(ai_agent)
    telegram_bot = TelegramBot(ai_agent, ssh_client)
    telegram_bot.set_appointment_service(appointment_service)
    ai_agent.set_telegram_bot(telegram_bot)
    fb_service.set_telegram_bot(telegram_bot)
    tiktok_service.set_telegram_bot(telegram_bot)

    # Initialize AgentMemoryService (self-improving brain)
    memory_service = AgentMemoryService()
    memory_service.set_http_client(llm_router._http_client)
    await memory_service.ensure_tables()
    ai_agent.set_memory_service(memory_service)
    telegram_bot.set_memory_service(memory_service)
    logger.info("[MemoryService] Self-learning memory engine initialized ✓")


    # 3. Attach to app state for dependency injection in routers
    app.state.llm_router = llm_router
    app.state.ssh_client = ssh_client
    app.state.message_cache = message_cache
    app.state.fb_service = fb_service
    app.state.tiktok_service = tiktok_service
    app.state.browser_agent = browser_agent
    app.state.ai_agent = ai_agent
    app.state.telegram_bot = telegram_bot
    app.state.appointment_service = appointment_service

    # 4. Start background workers
    telegram_task = asyncio.create_task(telegram_bot.start_polling())
    fb_scan_task = asyncio.create_task(facebook_periodic_scan_loop(fb_service))
    tiktok_scan_task = asyncio.create_task(tiktok_periodic_scan_loop(tiktok_service))
    reminder_task = asyncio.create_task(appointment_reminder_loop(appointment_service, telegram_bot))
    rtk_persist_task = asyncio.create_task(rtk_stats_persist_loop(llm_router))

    yield

    logger.info("Shutting down AI Agent & 9Router Service...")
    telegram_bot.stop()
    telegram_task.cancel()
    fb_scan_task.cancel()
    tiktok_scan_task.cancel()
    reminder_task.cancel()
    rtk_persist_task.cancel()
    try:
        await asyncio.gather(telegram_task, fb_scan_task, tiktok_scan_task, reminder_task, rtk_persist_task, return_exceptions=True)
    except Exception:
        pass
    # Persist any remaining RTK delta before shutdown
    await llm_router.save_stats_to_db()
    logger.info("[RTK-Persist] Final RTK stats flushed to DB on shutdown.")
    # Gracefully close the autonomous browser context
    await browser_agent.close()


app = FastAPI(
    title="9Router AI Gateway & Automation Microservice",
    description="Python Async FastAPI microservice with 9Router OpenAI-compatible Gateway, Telegram Bot, Facebook Messenger & TikTok Automation",
    version="2.0.0",
    lifespan=lifespan,
)

# Gzip Compression (reduces large JSON payloads by 85%)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(health.router)
app.include_router(facebook.router)
app.include_router(tiktok.router)
app.include_router(openai_gateway.router)
