# MLflow tracking server with a PostgreSQL backend driver.
# Pinned versions keep the local stack reproducible (invariant I6).
FROM python:3.12-slim

# psycopg2-binary provides the postgresql+psycopg2 driver MLflow uses for its backend store.
RUN pip install --no-cache-dir \
    "mlflow==2.16.2" \
    "psycopg2-binary==2.9.9"

EXPOSE 5000

# The concrete command (host/port/backend/artifacts) is supplied by docker-compose.yml
# so connection details stay in one place.
ENTRYPOINT []
