FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 civicbridge \
    && chown civicbridge:civicbridge /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=civicbridge:civicbridge . .

USER civicbridge
RUN python scripts/init_env.py \
    && for service in . revenue_service municipal_service identity_service; do \
         (cd "$service" && DJANGO_DEBUG=0 python manage.py collectstatic --noinput --verbosity 0) || exit 1; \
       done \
    && rm .env private/identity.pem \
    && rmdir private

EXPOSE 10000
CMD ["python", "scripts/run_hosted.py"]
