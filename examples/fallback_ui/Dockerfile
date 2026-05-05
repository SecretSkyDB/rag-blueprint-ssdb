# syntax=docker/dockerfile:1.6
#
# ssdb-rag-fallback-ui — tiny chat UI we control.
# Used as Option 2 in chat-ui-overlay.yaml.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py        /app/app.py
COPY templates/    /app/templates/

ENV PORT=3000
EXPOSE 3000

CMD ["python", "app.py"]
