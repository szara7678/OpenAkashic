"""Portable methods-only reader/writer. No private vault or news ingestion routes."""
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from app.research import WEB
from app.research_methods import router, method_store
from app.research_method_revisions import router as revision_router

app = FastAPI(title="OpenAkashic Methods", version="0.2.0", docs_url="/research/docs", openapi_url="/research/openapi.json")
app.include_router(router)
app.include_router(revision_router)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-transform"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    example = request.url.path.startswith("/research/methods/design-lab/") and request.url.path.endswith(".html")
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; form-action 'none'; object-src 'none'; frame-ancestors 'self'; base-uri 'none'"
        if example else "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
    return response


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(WEB / "methods-explore.html")


@app.get("/research/health")
def health():
    method_store()
    return {"status": "ok", "service": "openakashic-methods", "scope": "public_methods_only"}


@app.get("/graph", include_in_schema=False)
@app.get("/graph/", include_in_schema=False)
@app.get("/research/", include_in_schema=False)
@app.get("/research/methods/", include_in_schema=False)
def home():
    return FileResponse(WEB / "methods-explore.html")


@app.get("/research/methods/design-lab/", include_in_schema=False)
def design_lab():
    return FileResponse(WEB / "design-lab/index.html")


@app.get("/research/methods/design-lab/results.json", include_in_schema=False)
def design_report():
    report = Path(method_store().db_path).parent / "method-design-lab-report.json"
    if not report.is_file():
        raise HTTPException(404, "Historic synthetic design report not installed")
    return FileResponse(report)


@app.get("/research/methods/design-lab/{asset}", include_in_schema=False)
def design_asset(asset: Literal["lab.css", "lab.js"]):
    return FileResponse(WEB / "design-lab" / asset)


@app.get("/research/methods/design-lab/{condition}/{asset}", include_in_schema=False)
def design_example(condition: Literal["unaided", "direct", "retrieval"], asset: Literal["exhibition.html", "exhibition.css", "exhibition.js", "workshop.html", "workshop.css", "workshop.js"]):
    return FileResponse(WEB / "design-lab" / condition / asset)


@app.get("/research/{asset}", include_in_schema=False)
def asset(asset: Literal["methods.js", "methods.css", "methods-graph.js", "methods-kpi.html", "methods-kpi.js", "methods-explore.js", "methods-explore.css"]):
    return FileResponse(WEB / asset)


@app.get("/research/methods/library/", include_in_schema=False)
def methods_library():
    return FileResponse(WEB / "methods.html")
