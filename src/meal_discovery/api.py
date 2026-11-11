"""Real-catalog tools, bounded assistant, evaluations and the built product UI."""

import json
import logging
import os
import re
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

from .api_models import (CuisinesResult, ErrorResponse, Health, ItemResult, Provenance,
                         SearchParams, SearchResult, DiscoveryResult, RecommendationParams,
                         RecommendationResult, AssistantRequest, AssistantResponse)
from .catalog import (CatalogUnavailable, catalog_cuisines, catalog_item,
                      catalog_metadata, search_catalog)
from .discovery import discover
from .assistant import GEMINI_COOLDOWN, GEMINI_MAX_ATTEMPTS, GEMINI_TOTAL_TIMEOUT, HttpPlanner, run_assistant
from .serving import recommend
from .cloud_limits import PublicDemoGuard

logger = logging.getLogger("meal_discovery.api")


class CatalogReader:
    def __init__(self, index: Path, *, allow_test_data=False):
        self.index = index
        self.options = {"allow_test_data": allow_test_data}

    def metadata(self):
        manifest = catalog_metadata(self.index, **self.options)
        try:
            return Provenance.model_validate(manifest).model_dump()
        except ValidationError as error:
            raise CatalogUnavailable("Invalid catalog metadata") from error

    def cuisines(self):
        return catalog_cuisines(self.index, **self.options)

    def item(self, vendor_id, product_id):
        return catalog_item(self.index, vendor_id, product_id, **self.options)

    def search(self, params):
        return search_catalog(self.index, **params.model_dump(), **self.options)


def get_reader(request: Request) -> CatalogReader:
    return request.app.state.catalog_reader


Reader = Annotated[CatalogReader, Depends(get_reader)]
Identifier = Annotated[str, PathParam(min_length=1, max_length=200)]


def create_app(index: Path | None = None) -> FastAPI:
    application = FastAPI(
        title="Meal Discovery AI", version="0.8.0",
        description="Read-only discovery over the official historical Singapore catalog. Prices are normalized dataset values, not currency. No live availability or allergy guarantees.",
        responses={422: {"model": ErrorResponse, "description": "Invalid query parameters"},
                   503: {"model": ErrorResponse, "description": "Verified catalog unavailable"}},
    )
    application.state.catalog_reader = CatalogReader(
        Path(index) if index is not None else Path(os.environ.get("MEAL_CATALOG_INDEX", "data/processed/singapore-catalog-v1.sqlite")))
    application.state.serving_index = Path(os.environ.get("MEAL_SERVING_INDEX", "data/processed/singapore-serving-v1.sqlite"))
    application.add_middleware(PublicDemoGuard, enabled=os.environ.get("MEAL_PUBLIC_MODE") == "1")

    @application.middleware("http")
    async def request_trace(request: Request, call_next):
        request.state.request_id = uuid4().hex
        started = perf_counter()
        response = await call_next(request)
        elapsed = (perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Server-Timing"] = f"app;dur={elapsed:.2f}"
        # Route template excludes item IDs; query strings and bodies are never logged here.
        route = request.scope.get("route")
        logger.info(json.dumps({"request_id": request.state.request_id, "method": request.method,
                                "route": getattr(route, "path", "unmatched"),
                                "status": response.status_code, "elapsed_ms": round(elapsed, 2)}))
        return response

    def error(request, status, code, message, issues=None):
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": message, "request_id": request.state.request_id,
            "issues": issues or []}})

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exception):
        issues = [{"location": list(issue["loc"]), "message": issue["msg"], "type": issue["type"]}
                  for issue in exception.errors()]
        return error(request, 422, "invalid_request", "Check the query parameters.", issues)

    async def unavailable(request, exception):
        # Never expose filesystem paths, SQL, or source rows through operational errors.
        return error(request, 503, "catalog_unavailable", "The verified catalog is unavailable. Prepare the official index and check configuration.")

    for exception_type in (CatalogUnavailable, sqlite3.Error, OSError, json.JSONDecodeError, ResponseValidationError):
        application.add_exception_handler(exception_type, unavailable)

    @application.exception_handler(ValueError)
    async def invalid_domain_query(request, exception):
        return error(request, 422, "invalid_request", str(exception))

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request, exception):
        codes = {404: "not_found", 405: "method_not_allowed"}
        return error(request, exception.status_code, codes.get(exception.status_code, "http_error"), str(exception.detail))

    @application.get("/health", response_model=Health, tags=["operations"])
    def health():
        return {"status": "ok"}

    @application.get("/ready", response_model=Health, tags=["operations"])
    def ready(reader: Reader):
        reader.metadata()
        return {"status": "ready"}

    @application.get("/v1/catalog/meta", response_model=Provenance, tags=["catalog"])
    def metadata(reader: Reader):
        return reader.metadata()

    @application.get("/v1/catalog/cuisines", response_model=CuisinesResult, tags=["catalog"])
    def cuisines(reader: Reader):
        return reader.cuisines()

    @application.get("/v1/catalog/search", response_model=SearchResult, tags=["catalog"])
    def search(params: Annotated[SearchParams, Query()], reader: Reader):
        return reader.search(params)

    @application.get("/v1/discovery/search", response_model=DiscoveryResult, tags=["discovery"])
    def discovery(params: Annotated[SearchParams, Query()], reader: Reader):
        return discover(reader.index, **params.model_dump(), **reader.options)

    def recommendations_for(arguments):
        params = RecommendationParams.model_validate(arguments)
        result = recommend(application.state.serving_index,
                         [(seed.vendor_id, seed.product_id) for seed in params.seeds],
                         cuisine=params.cuisine, min_price=params.min_price, max_price=params.max_price, limit=params.limit)
        if result["provenance"]["source_database_sha256"] != application.state.catalog_reader.metadata()["source_database_sha256"]:
            raise CatalogUnavailable("Recommendation and catalog sources differ")
        return result

    @application.post("/v1/recommendations", response_model=RecommendationResult, tags=["recommendations"])
    def recommendations(params: RecommendationParams):
        return recommendations_for(params.model_dump())

    @application.post("/v1/assistant", response_model=AssistantResponse, tags=["assistant"])
    def assistant(params: AssistantRequest, reader: Reader):
        return run_assistant(params, reader, recommendations_for)

    @application.get("/v1/system", tags=["operations"])
    def system():
        from urllib.request import urlopen
        from urllib.parse import urlsplit
        planner = HttpPlanner()
        available = False
        if planner.provider == "local" and urlsplit(planner.endpoint).hostname in {"localhost", "127.0.0.1", "::1"}:
            try:
                with urlopen(planner.endpoint.rstrip("/") + "/health", timeout=1) as response:
                    available = response.status == 200
            except OSError:
                pass
        remote = planner.provider in {"gemini", "openai"}
        status = "configured_unverified" if remote and planner.configured else "ready" if available else "unavailable"
        cooldown = GEMINI_COOLDOWN.snapshot() if planner.provider == "gemini" else None
        if cooldown and cooldown["paused"]:
            status = "temporarily_unavailable"
        commit = os.environ.get("RENDER_GIT_COMMIT", "")
        return {"api_version": "0.8.0", "deployment_commit": commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None,
                "assistant": {"provider": planner.provider, "model": planner.model,
                "available": available, "configured": planner.configured, "status": status,
                "reliability": {"max_attempts": GEMINI_MAX_ATTEMPTS, "total_budget_seconds": GEMINI_TOTAL_TIMEOUT,
                                "cooldown": cooldown}
                               if planner.provider == "gemini" else None,
                "openai_configured": bool(planner.key and planner.model and planner.provider == "openai")},
                "recommendations_ready": application.state.serving_index.is_file(),
                "semantic_status": "experimental_pilot_not_used_by_product"}

    @application.get("/v1/evaluations", tags=["evaluations"])
    def evaluations():
        directory = Path(os.environ.get("MEAL_EVALUATIONS_DIR", str(Path(__file__).resolve().parents[2] / "evaluations/results")))
        reports = []
        for identifier, filename in (("recommendation", "singapore-official-validation-v2.json"),
                                     ("retrieval", "retrieval-development-v1.json")):
            path = directory / filename
            if not path.is_file():
                continue
            report = json.loads(path.read_text(encoding="utf-8"))
            if identifier == "recommendation":
                reports.append({"id": identifier, "kind": "offline_next_basket_validation", "users": report["evaluation"]["users"],
                                "protocol": report["protocol"], "models": report["models"], "limitations": report["limitations"]})
            else:
                reports.append({"id": identifier, "kind": report["kind"], "products": report["retrieval_manifest"]["indexed_products"],
                                "queries": len(report["queries"]), "models": report["summary"], "limitations": report["limitations"]})
        assistant_report = None
        path = next((directory / name for name in ("product-flow-v2.json", "product-flow-v1.json") if (directory / name).is_file()), directory / "product-flow-v1.json")
        if path.is_file():
            recorded = json.loads(path.read_text(encoding="utf-8"))
            assistant_report = {key: recorded[key] for key in (
                "kind", "passed", "total", "catalog_items_checked", "llm_calls", "tokens", "latency_ms", "limitations")}
            assistant_report["model"] = recorded["local_model_configuration"]["model"]
            assistant_report["report_version"] = path.stem
            assistant_report["live_gemini_tested"] = False
        conversation_report = None
        path = next((directory / name for name in ("conversation-development-summary-v2.json", "conversation-development-summary-v1.json")
                     if (directory / name).is_file()), directory / "conversation-development-summary-v1.json")
        if path.is_file():
            conversation_report = json.loads(path.read_text(encoding="utf-8"))
        ai_report = None
        path = directory / "ai-pipeline-summary-v1.json"
        if path.is_file():
            ai_report = json.loads(path.read_text(encoding="utf-8"))
        public_report = None
        path = next((directory / name for name in ("public-assistant-summary-v3.json", "public-assistant-summary-v2.json", "public-assistant-summary-v1.json")
                     if (directory / name).is_file()), directory / "public-assistant-summary-v1.json")
        if path.is_file():
            public_report = json.loads(path.read_text(encoding="utf-8"))
        relevance_report = None
        path = next((directory / name for name in ("relevance-decision-v2.json", "relevance-decision-v1.json")
                     if (directory / name).is_file()), directory / "relevance-decision-v1.json")
        if path.is_file():
            relevance_report = json.loads(path.read_text(encoding="utf-8"))
        return {"schema_version": 1, "reports": reports, "assistant_evaluation": assistant_report,
                "conversation_evaluation": conversation_report, "ai_evaluation": ai_report,
                "public_assistant_evaluation": public_report, "relevance_evaluation": relevance_report,
                "official_test_evaluated": False}

    @application.get("/v1/catalog/items/{vendor_id}/{product_id}", response_model=ItemResult,
                     responses={404: {"model": ErrorResponse, "description": "Item not found"}}, tags=["catalog"])
    def item(vendor_id: Identifier, product_id: Identifier, reader: Reader):
        result = reader.item(vendor_id, product_id)
        if result is None:
            raise HTTPException(404, "Item not found in the historical catalog.")
        return result

    web = Path(os.environ.get("MEAL_WEB_DIST", str(Path(__file__).resolve().parents[2] / "apps/web/dist")))
    if (web / "assets").is_dir():
        application.mount("/assets", StaticFiles(directory=web / "assets"), name="web-assets")

    @application.get("/", include_in_schema=False)
    def web_index():
        if not (web / "index.html").is_file():
            raise HTTPException(503, "Build the React interface with npm run build in apps/web.")
        return FileResponse(web / "index.html", headers={"Cache-Control": "no-cache"})

    return application


app = create_app()
