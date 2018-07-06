from vibora import Vibora
from vibora.static import StaticHandler
from vibora.responses import JsonResponse
from pathlib import Path

p = Path("static")
if not p.exists():
    p = Path("tests/static")
    if not p.exists():
        raise Exception("Path no exist")

app = Vibora(static=StaticHandler(paths=[str(p)]))


@app.route("/alive", methods=["GET"])
async def alive():
    return JsonResponse({"yes": ":)"})


def get_app():
    app.run(debug=False, verbose=False, host="localhost", port=8888, block=False)
    return app


if __name__ == "__main__":
    print("alive")
    app.run(debug=False, host="localhost", port=8888, workers=2)
