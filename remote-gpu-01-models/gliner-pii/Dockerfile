FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    gliner \
    fastapi \
    uvicorn \
    huggingface-hub

WORKDIR /app
COPY app.py .

EXPOSE 8020
CMD ["python", "app.py"]
