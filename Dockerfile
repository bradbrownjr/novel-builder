FROM python:3.12-slim

# ffmpeg: audiobook MP3/M4B compilation
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY novel_builder/ ./novel_builder/
COPY novel-builder.py .

# User story files, checkpoints, and output live here.
# Mount a host directory to /workspace to persist data across container restarts.
ENV NOVEL_BUILDER_WORKSPACE=/workspace
VOLUME ["/workspace"]

# Ollama server URL — override at runtime, e.g. -e OLLAMA_HOST=http://192.168.1.x:11434
ENV OLLAMA_HOST=""

EXPOSE 8080

CMD ["python", "-m", "novel_builder", "--web", "--port", "8080"]
