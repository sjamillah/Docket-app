FROM python:3.12-slim-bookworm

# curl is what the container health check uses; nothing else needs installing.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --create-home docket

WORKDIR /app

# Dependencies resolve from the project file alone, so this layer survives a
# code change.
COPY pyproject.toml ./
COPY scripts/install-deps.sh ./scripts/
RUN bash scripts/install-deps.sh

COPY --chown=docket:docket docket ./docket

USER docket
EXPOSE 8080

# Two workers because the tasks are small; the proxy is what absorbs the
# connection count, not this number.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", \
     "--timeout", "45", "--graceful-timeout", "40", "--access-logfile", "-", \
     "docket.app:app"]
