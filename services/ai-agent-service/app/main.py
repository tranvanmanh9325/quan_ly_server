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
from app.services.appointment_service import AppointmentService
from app.services.ai_agent import AiAgentService
from app.services.browser_agent import BrowserAgentService
from app.services.telegram_bot import TelegramBot
from app.routers import health, facebook, openai_gateway

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up AI Agent & 9Router Service (Python)...")

    # 1. Initialize core 9Router Engine & Infrastructure
    llm_router = LlmRouter()
    ssh_client = SshClient()
    message_cache = FacebookMessageCache()

    # 2. Initialize domain services with bidirectional wiring
    appointment_service = AppointmentService(llm_router)
    fb_service = FacebookService(message_cache, appointment_service=appointment_service)
    browser_agent = BrowserAgentService()
    ai_agent = AiAgentService(llm_router, ssh_client, message_cache, fb_service)
    ai_agent.set_appointment_service(appointment_service)
    fb_service.set_ai_agent(ai_agent)
    ai_agent.set_browser_agent(browser_agent)
    telegram_bot = TelegramBot(ai_agent, ssh_client)
    telegram_bot.set_appointment_service(appointment_service)
    fb_service.set_telegram_bot(telegram_bot)

    # 3. Attach to app state for dependency injection in routers
    app.state.llm_router = llm_router
    app.state.ssh_client = ssh_client
    app.state.message_cache = message_cache
    app.state.fb_service = fb_service
    app.state.browser_agent = browser_agent
    app.state.ai_agent = ai_agent
    app.state.telegram_bot = telegram_bot
    app.state.appointment_service = appointment_service

    # 4. Start background workers
    telegram_task = asyncio.create_task(telegram_bot.start_polling())
    fb_scan_task = asyncio.create_task(facebook_periodic_scan_loop(fb_service))

    yield

    logger.info("Shutting down AI Agent & 9Router Service...")
    telegram_bot.stop()
    telegram_task.cancel()
    fb_scan_task.cancel()
    try:
        await asyncio.gather(telegram_task, fb_scan_task, return_exceptions=True)
    except Exception:
        pass
    # Gracefully close the autonomous browser context
    await browser_agent.close()


app = FastAPI(
    title="9Router AI Gateway & Automation Microservice",
    description="Python Async FastAPI microservice with 9Router OpenAI-compatible Gateway, Telegram Bot & Facebook Messenger Automation",
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
app.include_router(openai_gateway.router)
