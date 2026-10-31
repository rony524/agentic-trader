FROM python:3.12-slim
WORKDIR /app
COPY services/trader/pyproject.toml .
COPY services/trader/src ./src
RUN pip install --no-cache-dir -e .
COPY config/ ./config/
EXPOSE 8000
CMD ["uvicorn", "trader.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
