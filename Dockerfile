FROM python:3.12-slim

# ffmpeg for M4B audiobook compilation
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY novel-builder.py .
COPY novel_builder/ ./novel_builder/

# Workspace holds YAML story files, output, and checkpoint state
VOLUME ["/app/workspace"]

ENV OLLAMA_HOST=http://ollama:11434

EXPOSE 8080

CMD ["python", "-m", "novel_builder", "--web", "--port", "8080"]
