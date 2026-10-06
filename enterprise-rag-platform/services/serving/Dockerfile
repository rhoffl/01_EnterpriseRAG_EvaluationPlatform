FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml /app/
COPY packages/rag_core /app/packages/rag_core
COPY services/serving /app/services/serving
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/packages/rag_core:/app/services/serving
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

