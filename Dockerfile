FROM python:3.12-slim-bookworm

# No curl: the container health check shells out to python, which is already
# here. Nothing else in the image needs installing.
RUN useradd --system --uid 10001 --create-home docket

WORKDIR /app

# Dependencies resolve from the project file alone, so this layer survives a
# code change. The project itself is never installed: that would drop an
# egg-info directory into the tree, and nothing needs it — the package sits
# at /app/docket and pytest finds it through pythonpath.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > deps.txt \
 && pip install --no-cache-dir -r deps.txt \
 && rm deps.txt

COPY --chown=docket:docket docket ./docket

USER docket
EXPOSE 8080

# Two workers because the tasks are small; the proxy is what absorbs the
# connection count, not this number.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", \
     "--timeout", "45", "--graceful-timeout", "40", "--access-logfile", "-", \
     "docket.app:app"]
