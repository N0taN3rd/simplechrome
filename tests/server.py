from vibora import Vibora
from vibora.static import StaticHandler
from vibora.responses import JsonResponse, RedirectResponse
from pathlib import Path
import asyncio

p = Path("static")
if not p.exists():
    p = Path("tests/static")
    if not p.exists():
        raise Exception("Path no exist")

app = Vibora(static=StaticHandler(paths=[str(p)]))


@app.route("/alive", methods=["GET"])
async def alive():
    return JsonResponse({"yes": ":)"})


@app.route("/static/never-loads1.html", methods=["GET"])
async def never_load():
    await asyncio.sleep(6)
    return RedirectResponse("http://localhost:8888/static/never-loads.html")


def get_app():
    app.run(debug=False, host="localhost", port=8888, block=False, workers=1)
    return app


if __name__ == "__main__":
    print("alive")
    app.run(debug=False, host="localhost", port=8888, workers=2)
