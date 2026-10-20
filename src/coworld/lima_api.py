"""Bind the unchanged native API to the private game-pod loopback interface."""

import runpy

api = runpy.run_path("/shared_volume/api.py", run_name="coworld_native_api")
app = api["app"]


@app.get("/coworld-healthz")
def health():
    return "ok\n"


app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
