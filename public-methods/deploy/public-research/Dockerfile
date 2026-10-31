FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN pip install --no-cache-dir fastapi==0.135.3 pydantic==2.13.0 uvicorn==0.44.0 tiktoken==0.14.0 && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"
WORKDIR /srv/openakashic/api
COPY api/app/research.py api/app/research_connectors.py api/app/research_store.py api/app/research_graph.py api/app/research_graph_store.py api/app/research_knowledge.py api/app/research_intake_context.py api/app/research_main.py api/app/research_references.py api/app/research_passages.py api/app/research_context.py api/app/research_adaptive_context.py api/app/research_changes.py api/app/utils.py ./app/
COPY api/scripts/public_news_providers.py ./scripts/
COPY api/app/research_memory.py ./app/
COPY api/app/research_time.py ./app/
COPY api/app/research_methods.py api/app/research_method_store.py api/app/research_method_search.py api/app/research_method_context.py ./app/
COPY api/app/research_method_graph.py api/app/research_method_evidence.py api/app/research_evidence_refs.py api/app/research_evidence_units.py ./app/
COPY web/research /srv/openakashic/web/research
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/research/health',timeout=3).read()"
CMD ["python", "-m", "uvicorn", "app.research_main:app", "--host", "0.0.0.0", "--port", "8080"]
