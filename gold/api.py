"""HTTP contract and process lifetime for the gold service."""
import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from .chat import Conversation
from .routing import Groq
from .runtime import configured_store
from .sips import Plans
from .store import Problem


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Message(Input):
    message: str = Field(min_length=1, max_length=1500)


class Amount(Input):
    amount: str = Field(max_length=32, examples=["333.33"])


class Purchase(Input):
    quote_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Sip(Amount):
    frequency: Literal["daily", "weekly", "monthly"]
    start: date
    anchor_day: int | None = Field(default=None, ge=1, le=31)


class BodyLimit:
    """Bound bytes before JSON decoding, including chunked requests."""
    def __init__(self, app, maximum=8192):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        data = bytearray()
        while True:
            part = await receive()
            if part["type"] == "http.disconnect":
                return
            data.extend(part.get("body", b""))
            if len(data) > self.maximum:
                return await JSONResponse({"detail": "Request too large."}, 413)(scope, receive, send)
            if not part.get("more_body"):
                break

        async def buffered():
            nonlocal data
            if data is not None:
                body, data = bytes(data), None
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, buffered, send)


async def scheduler(plans):
    while True:
        try:
            await asyncio.to_thread(plans.run_due)
        except sqlite3.OperationalError:
            logging.getLogger(__name__).exception("scheduler_storage_error")
        await asyncio.sleep(15)


def create_app(store=None, groq=None, run_scheduler=True):
    store = store or configured_store()
    if groq is None and os.getenv("GROQ_API_KEY"):
        groq = Groq(os.environ["GROQ_API_KEY"], os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"))
    chat = Conversation(store, groq)
    plans = Plans(store)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        task = asyncio.create_task(scheduler(plans)) if run_scheduler else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Digital Gold", version="1.0.0", lifespan=lifespan,
                  description="Authenticated simulated INR ledger. Money values are decimal strings.")
    app.add_middleware(BodyLimit)
    bearer = HTTPBearer(auto_error=False)

    def identify(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None:
            raise Problem(401, "Supply a bearer credential.")
        return store.authenticate(credentials.credentials)

    owner = Annotated[str, Depends(identify)]
    key = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")]
    page = Annotated[int, Query(ge=1, le=200)]
    offset_param = Annotated[int, Query(ge=0)]

    @app.exception_handler(Problem)
    async def problem(_, exc):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
        return JSONResponse({"detail": str(exc)}, status_code=exc.status, headers=headers)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(_, exc):
        logging.getLogger(__name__).error("sqlite_operation_failed code=%s", getattr(exc, "sqlite_errorname", None))
        return JSONResponse({"detail": "Storage unavailable. Retry with the same key."}, 503)

    @app.get("/health")
    def health():
        with store.connection() as db:
            db.execute("SELECT 1 FROM events LIMIT 1").fetchone()
        return {"status": "ok"}

    @app.post("/chat")
    def conversation(body: Message, user: owner, command_key: key):
        return chat.reply(user, body.message, command_key)

    @app.post("/quotes")
    def quote(body: Amount, user: owner, command_key: key):
        return store.quote(user, body.amount, command_key)

    @app.get("/quotes/pending")
    def pending(user: owner):
        with store.connection() as db:
            return {"quote": store.pending(db, user)}

    @app.post("/purchases")
    def purchase(body: Purchase, user: owner, command_key: key):
        return store.buy(user, body.quote_id, command_key)

    @app.get("/ledger")
    def ledger(user: owner, limit: page = 100, offset: offset_param = 0):
        return store.ledger(user, limit, offset)

    @app.post("/sips")
    def create_sip(body: Sip, user: owner, command_key: key):
        return plans.create(user, body.amount, body.frequency, body.start, command_key, body.anchor_day)

    @app.get("/sips")
    def sips(user: owner, limit: page = 100, offset: offset_param = 0):
        return plans.list(user, limit, offset)

    @app.post("/sips/{sip_id}/{action}")
    def change_sip(sip_id: str, action: Literal["pause", "cancel"], user: owner, command_key: key):
        return plans.change(user, sip_id, action, command_key)

    @app.get("/events")
    def trace(user: owner, after: offset_param = 0, limit: page = 100):
        return store.trace(user, after, limit)

    return app
