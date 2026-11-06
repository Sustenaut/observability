# Observability's evaluator: `observability evaluate`, run every two minutes by the
# CronJob in k8s/evaluator.yaml. Build from the repository's root:
#   podman build -t observability .
# It holds no credentials: its BigQuery key and storage token are mounted on the server.
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY evaluator-requirements.lock pyproject.toml README.md LICENSE /tmp/build/
COPY src/ /tmp/build/src/
RUN pip install --require-hashes -r /tmp/build/evaluator-requirements.lock \
    && pip install --no-deps /tmp/build && rm -rf /tmp/build
RUN useradd --create-home --uid 1000 app
USER app
CMD ["observability", "evaluate"]
