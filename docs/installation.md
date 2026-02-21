# Installation

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally or on a network host
- A model pulled in Ollama (e.g., `ollama pull gemma3:12b`)

## Debian / Ubuntu

```bash
# Install Python and venv (if not already present)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

# Clone the repo
git clone https://github.com/bradbrownjr/novel-builder.git
cd novel-builder

# Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Other Linux / macOS

```bash
git clone https://github.com/bradbrownjr/novel-builder.git
cd novel-builder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dependencies are minimal: `pyyaml`, `requests`, and `flask`.

## Installing Ollama

If Ollama isn't installed on the generation host yet:

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Pull models
ollama pull gemma3:12b     # Generation model
ollama pull gemma3:1b      # Summary model (fast, lightweight)

# Verify it's running
curl http://localhost:11434/api/tags
```

### Remote Ollama

If Ollama runs on a different machine on your LAN, point Novel Builder at it:

```bash
# CLI — pass the flag or set the env var
export OLLAMA_HOST=http://192.168.1.x:11434
python -m novel_builder

# Or pass it directly
python -m novel_builder --host http://192.168.1.x:11434
```

In the **web UI**, enter the host URL in the config panel — it saves to disk and persists across restarts.

## Running as a Service (optional)

If you want the web UI to run on boot:

```bash
# Create a systemd service
sudo tee /etc/systemd/system/novel-builder.service > /dev/null <<EOF
[Unit]
Description=Novel Builder Web UI
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/python -m novel_builder --web --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now novel-builder
```

Check status: `sudo systemctl status novel-builder`

---

← [Back to README](../README.md)
