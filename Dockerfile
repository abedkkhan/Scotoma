FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scotoma ./scotoma

RUN useradd --create-home --uid 10001 scotoma && \
    mkdir -p /tmp/scotoma-cache /tmp/scotoma-jobs && \
    chown -R scotoma:scotoma /tmp/scotoma-cache /tmp/scotoma-jobs
USER scotoma

CMD ["sh", "-c", "uvicorn scotoma.server:app --host 0.0.0.0 --port ${PORT}"]
