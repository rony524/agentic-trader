FROM python:3.12-slim
WORKDIR /app
COPY services/trader/pyproject.toml .
COPY services/trader/src ./src
# alpaca: executor · eth: approval signature verification (nothing can be approved without it) · postgres: Neon
RUN pip install --no-cache-dir -e ".[alpaca,eth,postgres]"
COPY config/ ./config/
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn trader.api.main:app --host 0.0.0.0 --port ${PORT}"]
