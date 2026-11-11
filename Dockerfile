FROM node:24.22.2-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MEAL_PUBLIC_MODE=1 LLM_PROVIDER=gemini LLM_MODEL=gemini-3.1-flash-lite \
    GEMINI_CALLS_PER_MINUTE=4 GEMINI_CALLS_PER_DAY=20 LLM_FALLBACK_PROVIDERS=groq \
    GROQ_MODEL=openai/gpt-oss-120b GROQ_CALLS_PER_MINUTE=10 GROQ_CALLS_PER_DAY=300 PORT=10000 \
    MEAL_WEB_DIST=/app/apps/web/dist MEAL_EVALUATIONS_DIR=/app/evaluations/results \
    MEAL_CATALOG_INDEX=/app/data/processed/singapore-catalog-v1.sqlite \
    MEAL_SERVING_INDEX=/app/data/processed/singapore-serving-v1.sqlite
WORKDIR /app
COPY pyproject.toml README.md LICENSE requirements-api.lock ./
COPY src/ ./src/
RUN pip install --no-cache-dir -c requirements-api.lock ".[api]"
COPY deploy/ ./deploy/
COPY scripts/fetch_deploy_artifact.py scripts/start_cloud.py ./scripts/
# Download only while building. Cold starts use the immutable, verified image.
RUN python scripts/fetch_deploy_artifact.py && chmod 444 data/processed/*
COPY --from=web /web/dist ./apps/web/dist
COPY evaluations/results/ ./evaluations/results/
RUN useradd --uid 10001 --no-create-home mesa
USER 10001
EXPOSE 10000
CMD ["python", "scripts/start_cloud.py"]
