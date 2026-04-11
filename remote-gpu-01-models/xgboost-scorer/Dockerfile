FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir 'setuptools<81' xgboost fastapi uvicorn numpy mlflow==2.13.2 boto3

WORKDIR /app
COPY app.py .

EXPOSE 8010
CMD ["python", "app.py"]
