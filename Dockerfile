FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir -U pip

COPY pyproject.toml /app/pyproject.toml
COPY app /app/app

RUN pip install --no-cache-dir .

ENV PORT=8080
EXPOSE 8080

CMD ["/bin/sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
