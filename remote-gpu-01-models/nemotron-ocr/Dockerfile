FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    nemotron-ocr==1.0.1 \
    fastapi \
    pillow \
    pytesseract \
    uvicorn \
    python-multipart \
    huggingface-hub

WORKDIR /app
COPY app.py .

EXPOSE 8021
CMD ["python", "app.py"]
