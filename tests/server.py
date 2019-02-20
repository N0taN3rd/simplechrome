import asyncio
from asyncio import AbstractEventLoop, get_event_loop as aio_get_event_loop, sleep as aio_sleep
from contextvars import ContextVar
from pathlib import Path

from vibora import Vibora
from vibora.responses import JsonResponse, RedirectResponse
from vibora.static import StaticHandler

p = Path("static")
if not p.exists():
    p = Path("tests/static")
    if not p.exists():
        raise Exception("Path no exist")

app = Vibora(static=StaticHandler(paths=[str(p)]))

event_loop: ContextVar[AbstractEventLoop] = ContextVar("event_loop")


@app.route("/alive", methods=["GET"])
async def alive():
    return JsonResponse({"yes": ":)"})


@app.route("/static/never-loads1.html", methods=["GET"])
async def never_load():
    loop = event_loop.get()
    if loop is None:
        loop = aio_get_event_loop()
        event_loop.set(loop)
    await aio_sleep(6, loop=loop)
    return RedirectResponse("http://localhost:8888/static/never-loads.html")


def get_app():
    app.run(debug=False, host="localhost", port=8888, block=False, workers=1)
    return app


if __name__ == "__main__":
    print("alive")
    app.run(debug=False, host="localhost", port=8888, workers=2)
