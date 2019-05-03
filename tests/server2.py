from asyncio import sleep
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.responses import PlainTextResponse, RedirectResponse, UJSONResponse
from starlette.staticfiles import StaticFiles

app = FastAPI()
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)


@app.get("/alive")
async def alive(*args, **kwargs) -> UJSONResponse:
    return UJSONResponse({"yes": ":)"})


@app.get("/never-loads")
async def never_load(*args, **kwargs) -> RedirectResponse:
    await sleep(6)
    return RedirectResponse(url="/should-never-get-here")


@app.get("/should-never-get-here")
async def never_load(*args, **kwargs) -> PlainTextResponse:
    return PlainTextResponse(
        "If you are simplechrome controlled browser why are you here? Otherwise welcome friend!"
    )


if __name__ == "__main__":
    print("alive")
    uvicorn.run(app, host="0.0.0.0", port=8888, loop="uvloop")
    # app.setup()
    # app.run(host="0.0.0.0", port=8888, workers=1, debug=True)
