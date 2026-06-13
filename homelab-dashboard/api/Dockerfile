FROM python:3.12-slim
WORKDIR /app
# ripgrep: required for Claude Code's Glob/Grep tools (chatbot inspection).
# Without it the chatbot reports "missing rg binary" and can't list/search files.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ripgrep \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY dashboard.html .
EXPOSE 8787
CMD ["python", "app.py"]
