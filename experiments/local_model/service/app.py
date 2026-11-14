"""No database, application integration, request logging, or persistence."""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .model import Encoder, InputError, MODEL_ID, REVISION, validate_texts

MAX_BODY_BYTES = 32768
QUEUE_WAIT_SECONDS = 2.0
logger = logging.getLogger('local_model_service')


class Overloaded(Exception):
    pass


class Admission:
    """One active task and one waiter, even if a client disconnects/cancels."""
    def __init__(self, wait_seconds=QUEUE_WAIT_SECONDS):
        self.lock = asyncio.Lock()
        self.occupied = 0
        self.wait_seconds = wait_seconds
        self.tasks = set()

    async def run(self, function, value):
        if self.occupied >= 2:
            raise Overloaded()
        self.occupied += 1

        async def work():
            try:
                try:
                    await asyncio.wait_for(self.lock.acquire(), timeout=self.wait_seconds)
                except TimeoutError:
                    raise Overloaded() from None
                try:
                    return await asyncio.to_thread(function, value)
                finally:
                    self.lock.release()
            finally:
                self.occupied -= 1

        task = asyncio.create_task(work())
        self.tasks.add(task)

        def finished(done):
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Consume detached errors without logging their contents.

        task.add_done_callback(finished)
        # Cancellation must not release the inference slot while its thread is running.
        return await asyncio.shield(task)

    async def drain(self):
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)


def error(status, code, message):
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status,
                        headers={'Cache-Control': 'no-store', **({'Retry-After': '1'} if status == 429 else {})})


def create_app(loader=Encoder, wait_seconds=QUEUE_WAIT_SECONDS):
    @asynccontextmanager
    async def lifespan(app):
        token = os.environ.get('TALENTMATCH_EMBED_TOKEN', '')
        if not 32 <= len(token) <= 256 or any(not 33 <= ord(c) <= 126 for c in token):
            raise RuntimeError('TALENTMATCH_EMBED_TOKEN must contain 32–256 printable non-whitespace ASCII characters.')
        app.state.token = token
        try:
            app.state.encoder = await asyncio.to_thread(loader)
        except Exception:
            raise RuntimeError('Local model initialization failed; verify pinned local model files.') from None
        try:
            yield
        finally:
            app.state.encoder = None
            await app.state.admission.drain()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.encoder = None
    app.state.token = None
    app.state.admission = Admission(wait_seconds)

    @app.get('/healthz')
    async def healthz():
        return {'status': 'ok'}

    @app.get('/readyz')
    async def readyz():
        if app.state.encoder is None:
            return error(503, 'not_ready', 'Local model is not ready.')
        return {'status': 'ready', 'model': MODEL_ID, 'revision': REVISION}

    @app.post('/embed')
    async def embed(request: Request):
        provided = request.headers.getlist('authorization')
        expected = app.state.token
        if expected is None or len(provided) != 1 or not secrets.compare_digest(provided[0].encode(), ('Bearer '+expected).encode()):
            return error(401, 'unauthorized', 'Service authentication required.')
        if app.state.encoder is None:
            return error(503, 'not_ready', 'Local model is not ready.')
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return error(415, 'content_type', 'Content-Type must be application/json.')
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return error(413, 'body_too_large', f'JSON body exceeds {MAX_BODY_BYTES} bytes.')
            body.extend(chunk)
        try:
            value = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeError, RecursionError):
            return error(400, 'invalid_json', 'Request body must contain valid UTF-8 JSON.')
        try:
            texts = validate_texts(value)
        except InputError as exc:
            return error(422, 'invalid_input', str(exc))
        try:
            vectors = await app.state.admission.run(app.state.encoder.embed, texts)
        except Overloaded:
            return error(429, 'overloaded', 'Inference capacity is busy; retry later.')
        except InputError as exc:
            return error(422, 'invalid_input', str(exc))
        except Exception:
            logger.error('Local embedding inference failed.')
            return error(503, 'inference_failed', 'Local embedding inference failed.')
        return JSONResponse({'model': MODEL_ID, 'revision': REVISION, 'embeddings': vectors},
                            headers={'Cache-Control': 'no-store'})

    return app

app = create_app()
