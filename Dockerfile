FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/app/data/fraud.db
COPY pyproject.toml requirements.lock ./
COPY fraud_service ./fraud_service
RUN pip install --no-cache-dir -c requirements.lock . \
    && useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "fraud_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
