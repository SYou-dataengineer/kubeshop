FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYSPARK_PYTHON=python3 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY streaming_job.py ./

CMD ["spark-submit", "--master", "local[2]", "--packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3", "/app/streaming_job.py"]
