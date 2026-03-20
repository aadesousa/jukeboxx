# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM python:3.12-alpine AS builder

RUN apk add --no-cache gcc musl-dev linux-headers libffi-dev

WORKDIR /build

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
RUN pip install --no-cache-dir rjsmin rcssmin

COPY frontend/ /frontend/
COPY scripts/minify.py /build/minify.py
RUN python3 /build/minify.py /frontend

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-alpine

RUN apk add --no-cache chromaprint curl

COPY --from=builder /install /usr/local
COPY backend/ /app/
COPY --from=builder /frontend/ /app/static/

WORKDIR /app

EXPOSE 8000

CMD ["uvicorn", "main:root_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
