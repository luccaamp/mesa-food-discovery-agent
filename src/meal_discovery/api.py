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
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

from .api_models import (CuisinesResult, ErrorResponse, Health, ItemResult, Provenance,
                         SearchParams, SearchResult, DiscoveryResult, RecommendationParams,
                         RecommendationResult, AssistantRequest, AssistantResponse)
from .catalog import (CatalogUnavailable, catalog_cuisines, catalog_item,
                      catalog_metadata, search_catalog)
from .discovery import discover
from .assistant import run_assistant
from .llm import describe, resilience
from .planner import IntentPlanner
from .context_popularity import recommend_here, regions as context_regions, slot_at, SLOT_LABELS
from .serving import recommend
from .cloud_limits import PublicDemoGuard
from .observability import HTTP, metrics_payload, record_turn, setup_tracing

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
        title="Mesa food discovery API", version="0.9.0",
        description="Read-only discovery over the official historical Singapore catalog. Prices are normalized dataset values, not currency. No live availability or allergy guarantees.",
        responses={422: {"model": ErrorResponse, "description": "Invalid query parameters"},
                   503: {"model": ErrorResponse, "description": "Verified catalog unavailable"}},
    )
    application.state.catalog_reader = CatalogReader(
        Path(index) if index is not None else Path(os.environ.get("MEAL_CATALOG_INDEX", "data/processed/singapore-catalog-v1.sqlite")))
    application.state.serving_index = Path(os.environ.get("MEAL_SERVING_INDEX", "data/processed/singapore-serving-v1.sqlite"))
    setup_tracing()
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
        HTTP.labels(getattr(route, "path", "unmatched"), request.method, str(response.status_code)).observe(elapsed / 1000)
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
        if not params.seeds:
            # Nothing selected: what people order in this region and time slot (Experiment 004).
            reader = application.state.catalog_reader
            here = recommend_here(reader.index, region=params.region, slot=params.slot, cuisine=params.cuisine,
                                  min_price=params.min_price, max_price=params.max_price,
                                  price_level=params.price_level, limit=params.limit, **reader.options)
            if here["items"]:
                rest = recommend(application.state.serving_index, [], cuisine=params.cuisine, min_price=params.min_price,
                                 max_price=params.max_price, price_level=params.price_level, limit=params.limit)
                chosen = {(item["vendor_id"], item["product_id"]) for item in here["items"]}
                items = here["items"] + [item for item in rest["items"]
                                         if (item["vendor_id"], item["product_id"]) not in chosen]
                return {**rest, "items": items[:params.limit],
                        "context": {key: here[key] for key in ("region", "slot", "slot_label")}}
        result = recommend(application.state.serving_index,
                         [(seed.vendor_id, seed.product_id) for seed in params.seeds],
                         cuisine=params.cuisine, min_price=params.min_price, max_price=params.max_price,
                         price_level=params.price_level, limit=params.limit)
        if result["provenance"]["source_database_sha256"] != application.state.catalog_reader.metadata()["source_database_sha256"]:
            raise CatalogUnavailable("Recommendation and catalog sources differ")
        return result

    if os.environ.get("WHATSAPP_WORKER") == "1":
        # Free hosting has no separate worker service: consume the WhatsApp queue in a daemon thread.
        import threading
        from .channels.whatsapp import build_from_environment
        worker = build_from_environment(application.state.catalog_reader, recommendations_for)
        if worker is not None:
            application.state.whatsapp_stop = threading.Event()
            threading.Thread(target=worker.run_forever, args=(application.state.whatsapp_stop,),
                             name="whatsapp-worker", daemon=True).start()
            logger.info("whatsapp_worker_started")
        else:
            logger.warning("whatsapp_worker_not_configured")

    @application.get("/v1/discovery/regions", tags=["discovery"],
                     summary="Order regions with names and the current time slot in Singapore")
    def discovery_regions():
        slot = slot_at()
        return {"regions": context_regions(), "slot": slot, "slot_label": SLOT_LABELS[slot],
                "note": "Regions are DHRD order geohash cells, named after the nearest town (approximate)."}

    @application.post("/v1/recommendations", response_model=RecommendationResult, tags=["recommendations"])
    def recommendations(params: RecommendationParams):
        return recommendations_for(params.model_dump())

    @application.post("/v1/assistant", response_model=AssistantResponse, tags=["assistant"])
    def assistant(params: AssistantRequest, reader: Reader):
        result = run_assistant(params, reader, recommendations_for)
        record_turn("planner", result)
        return result

    @application.post("/v1/agent", response_model=AssistantResponse, tags=["assistant"],
                      summary="Multi-step tool-calling agent (LangGraph)")
    def agent(params: AssistantRequest, reader: Reader):
        from .agent import run_agent
        result = run_agent(params, reader, recommendations_for)
        record_turn("agent", result)
        return result

    @application.post("/v1/agent/stream", tags=["assistant"], summary="Agent steps as Server-Sent Events",
                      response_class=StreamingResponse)
    def agent_stream(params: AssistantRequest, reader: Reader):
        from .agent import stream_agent

        def events():
            for event in stream_agent(params, reader, recommendations_for):
                if event["type"] == "result":
                    record_turn("agent_stream", event["response"])
                    event = {"type": "result", "response": AssistantResponse.model_validate(event["response"]).model_dump(mode="json")}
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @application.get("/metrics", include_in_schema=False)
    def metrics():
        from fastapi.responses import Response
        body, content_type = metrics_payload()
        return Response(body, media_type=content_type)

    @application.get("/v1/system", tags=["operations"])
    def system():
        from urllib.request import urlopen
        from urllib.parse import urlsplit
        planner = IntentPlanner()
        primary = planner.chat_model.models[0] if hasattr(planner.chat_model, "models") else planner.chat_model
        providers = describe(planner.chat_model) if planner.chat_model else []
        available = False
        if planner.provider == "local" and urlsplit(primary.endpoint).hostname in {"localhost", "127.0.0.1", "::1"}:
            try:
                with urlopen(primary.endpoint + "/health", timeout=1) as response:
                    available = response.status == 200
            except OSError:
                pass
        remote = planner.provider in {"gemini", "groq", "openai"}
        status = "configured_unverified" if remote and planner.configured else "ready" if available else "unavailable"
        cooldown = providers[0].get("cooldown") if providers else None
        configured_fallbacks = [entry for entry in providers[1:] if entry["configured"]]
        if cooldown and cooldown["paused"]:
            status = "degraded" if configured_fallbacks else "temporarily_unavailable"
        policy = resilience.RetryPolicy()
        commit = os.environ.get("RENDER_GIT_COMMIT", "")
        return {"api_version": "0.9.0", "deployment_commit": commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None,
                "assistant": {"provider": planner.provider, "model": planner.model,
                "available": available, "configured": planner.configured, "status": status,
                "reliability": {"max_attempts": policy.max_attempts, "total_budget_seconds": policy.total_timeout,
                                "cooldown": cooldown} if remote else None,
                "providers": providers,
                "openai_configured": any(entry["provider"] == "openai" and entry["configured"] for entry in providers)},
                "recommendations_ready": application.state.serving_index.is_file()}

    @application.get("/v1/evaluations", tags=["evaluations"])
    def evaluations():
        """The results the lab page shows; each one links to its raw report in evaluations/results."""
        directory = Path(os.environ.get("MEAL_EVALUATIONS_DIR", str(Path(__file__).resolve().parents[2] / "evaluations/results")))

        def load(name):
            path = directory / name
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

        discovery = None
        # Experiment 004: the official test run once it exists, otherwise the validation run.
        for stage in ("test", "validation"):
            recorded = load(f"discovery-{stage}-v1.json")
            if recorded:
                discovery = {"stage": recorded["stage"], "report": f"discovery-{stage}-v1.json",
                             "created_at": recorded["created_at_utc"], "targets": recorded["targets"],
                             "restaurants": recorded["restaurants"], "items": recorded["items"],
                             "intervals": recorded.get("intervals")}
                break
        agent_discovery = None
        for name in ("agent-discovery-v2.json", "agent-discovery-v1.json"):  # v2 repeats v1 without quota fallbacks
            recorded = load(name)
            if recorded:
                agent_discovery = {key: recorded[key] for key in ("arms", "cases", "provider", "model", "created_at_utc",
                                                                  "llm_usage") if key in recorded} | {"report": name}
                break
        agent_comparison = None
        recorded = load("agent-provider-reserved-v1.json")
        if recorded:  # held-out contracts, frozen before any tuning of the agent
            agent_comparison = {"created_at": recorded["created_at"], "split": "reserved", "summaries": recorded["summaries"]}
        red_team = []
        for provider in ("gemini", "groq"):
            recorded = load(f"red-team-v2-{provider}.json")
            if not recorded:
                continue
            for summary in recorded["summaries"]:
                by_risk = {}
                for row in recorded["cases"].get(summary["provider"], []):
                    risk = by_risk.setdefault(row["owasp"], {"owasp": row["owasp"], "cases": 0, "passed": 0})
                    risk["cases"] += 1
                    risk["passed"] += bool(row["passed"])
                red_team.append({**{k: summary[k] for k in ("provider", "model", "cases", "passed", "model_exercised",
                                                            "model_fallbacks")},
                                 "created_at": recorded["created_at"], "report": f"red-team-v2-{provider}.json",
                                 "by_risk": sorted(by_risk.values(), key=lambda risk: risk["owasp"])})
        retrieval = load("retrieval-development-v1.json")
        if retrieval:  # negative result: embeddings did not beat lexical search
            retrieval = {"products": retrieval["retrieval_manifest"]["indexed_products"],
                         "queries": len(retrieval["queries"]), "models": retrieval["summary"],
                         "report": "retrieval-development-v1.json"}
        return {"schema_version": 2, "discovery": discovery, "agent_discovery": agent_discovery,
                "agent_comparison": agent_comparison, "red_team": red_team, "retrieval": retrieval,
                "official_test_evaluated": bool(discovery and discovery["stage"] == "final_test")}

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
