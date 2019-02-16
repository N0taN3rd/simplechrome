from asyncio import sleep as aio_sleep
from pathlib import Path

import uvloop
from sanic import Sanic
from sanic.response import HTTPResponse, json, text

uvloop.install()


app = Sanic(name="simplechrome-test-server")
app.static("/static", str(Path(__file__).parent / "static"))


@app.route("/alive")
async def alive(request) -> HTTPResponse:
    return json({"yes": ":)"})


@app.route("/never-loads")
async def never_load(request) -> HTTPResponse:
    await aio_sleep(6)
    return request.redirect("should-never-get-here")


@app.route("/should-never-get-here")
async def never_load(request) -> HTTPResponse:
    return text(
        "If you are simplechrome controlled browser why are you here? Otherwise welcome friend!",
        status=404
    )


if __name__ == "__main__":
    print("alive")
    app.run(host="0.0.0.0", port=8888, workers=1, debug=True)
