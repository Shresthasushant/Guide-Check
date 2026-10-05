"""Guide Check backend.

Serves the five-page site in static/ and two API endpoints:

    GET  /api/suburbs   the NSW suburb list with each suburb's postcode, for
                        the form's dropdown and postcode auto-fill
    POST /api/check     runs the real trained model (src/serve.py) against a
                        suburb/postcode/property typed in by the user

Pages are served at clean URLs (/check, /how-to-use, ...) as well as at their
.html paths, which Flask's static handler covers. Run with:

    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000
"""
import os
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
import serve  # noqa: E402

app = Flask(__name__, static_folder="static", static_url_path="")

# Under gunicorn there is no __main__, so the first request would otherwise pay
# the 30-45s model load and hit the worker timeout. Set GUIDE_CHECK_PRELOAD=1 in
# the deployment environment (see Procfile) to load at import instead.
if os.environ.get("GUIDE_CHECK_PRELOAD") == "1":
    serve.load()

_suburbs_cache = None


def _suburbs():
    """[{"suburb": "BONDI", "postcode": "2026"}, ...], sorted by suburb.

    A suburb can appear against several postcodes in the sales data (boundary
    streets, data entry), so the postcode offered to the form is the most
    frequent one for that suburb -- the right default for the dropdown to
    auto-fill. The postcode field stays editable for the exceptions."""
    global _suburbs_cache
    if _suburbs_cache is None:
        _, _, _, _, feat, _, _ = serve.load()
        df = pd.DataFrame({
            "suburb": feat["suburb"].astype(str).str.strip().str.upper(),
            "postcode": feat["postcode"].astype(str).str.strip().str.zfill(4),
        })
        df = df[(df["suburb"] != "") & (df["suburb"] != "NAN")]
        counts = df.groupby(["suburb", "postcode"]).size().reset_index(name="n")
        best = (counts.sort_values(["suburb", "n", "postcode"],
                                   ascending=[True, False, True])
                      .drop_duplicates("suburb"))
        _suburbs_cache = [
            {"suburb": r.suburb, "postcode": r.postcode}
            for r in best.itertuples(index=False)
        ]
    return _suburbs_cache


def _clean(obj):
    """Make serve.py's output JSON-safe: numpy scalars/arrays, pandas Series
    and DataFrames all need converting."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, pd.DataFrame):
        return _clean(obj.reset_index(drop=True).to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return _clean(obj.to_dict())
    if isinstance(obj, (np.generic,)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return [_clean(v) for v in obj.tolist()]
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def _page(filename):
    return send_from_directory(app.static_folder, filename)


# Clean URLs, one explicit rule each. A catch-all /<page> rule would compete
# with Flask's own /<path:filename> static route (static_url_path is "") and
# which one wins is not worth relying on.
@app.get("/")
def index():
    return _page("index.html")


@app.get("/check")
def page_check():
    return _page("check.html")


@app.get("/how-to-use")
def page_how_to_use():
    return _page("how-to-use.html")


@app.get("/how-it-works")
def page_how_it_works():
    return _page("how-it-works.html")


@app.get("/limits")
def page_limits():
    return _page("limits.html")


@app.get("/healthz")
def healthz():
    """Cheap liveness probe. Deliberately does NOT touch serve.load() -- a
    health check that loads 1.2GB of model would time out and restart-loop the
    service. Whether the model is loaded is reported, not waited on."""
    return jsonify({
        "status": "ok",
        "model_loaded": serve.load.cache_info().currsize > 0,
    })


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "No such endpoint."}), 404
    return _page("404.html"), 404


@app.after_request
def cache_headers(resp):
    """HTML must not be cached (a redeploy has to be visible immediately);
    the CSS/JS/icon under /assets/ can be, briefly."""
    if request.path.startswith("/assets/"):
        # Overwrite rather than setdefault: send_from_directory has already put
        # "no-cache" here, because SEND_FILE_MAX_AGE_DEFAULT is unset.
        resp.headers["Cache-Control"] = "public, max-age=3600"
    elif resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/api/suburbs")
def api_suburbs():
    return jsonify(_suburbs())


@app.post("/api/check")
def api_check():
    body = request.get_json(force=True) or {}
    try:
        guide = body.get("guide")
        result = serve.value_manual(
            suburb=body["suburb"],
            postcode=body.get("postcode", "0000"),
            property_type=body.get("property_type", "house"),
            land_area_m2=body.get("land_area_m2"),
            address=body.get("address", "(entered manually)"),
            guide=float(guide) if guide not in (None, "") else None,
            bedrooms=body.get("bedrooms"),
            bathrooms=body.get("bathrooms"),
        )
        return jsonify(_clean(result))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Something went wrong scoring that property."}), 500


if __name__ == "__main__":
    print("Loading model...")
    serve.load()
    print(f"Ready. {len(_suburbs())} NSW suburbs indexed.")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
