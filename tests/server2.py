from asyncio import sleep
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.responses import PlainTextResponse, RedirectResponse, UJSONResponse
from starlette.staticfiles import StaticFiles
import logging

logger = logging.getLogger("test_server")
logger.setLevel(logging.DEBUG)


app = FastAPI()
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/alive")
async def alive() -> UJSONResponse:
    return UJSONResponse({"yes": ":)"})


@app.get("/never-loads")
async def never_load() -> RedirectResponse:
    logger.info("never loads")
    await sleep(6)
    return RedirectResponse(url="/should-never-get-here")


@app.get("/should-never-get-here")
async def should_not_be_here() -> PlainTextResponse:
    return PlainTextResponse(
        "If you are simplechrome controlled browser why are you here? Otherwise welcome friend!"
    )


if __name__ == "__main__":
    logger.info("alive")
    uvicorn.run(app, host="localhost", port=8888, loop="uvloop", debug=True)
