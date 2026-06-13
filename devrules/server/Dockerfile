FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py store.py ./
COPY static ./static

ENV DEVRULES_DATA=/data \
    DEVRULES_PORT=8799

EXPOSE 8799

CMD ["python", "server.py"]
