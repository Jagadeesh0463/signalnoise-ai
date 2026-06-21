# Deployment

## Local Development

```bash
git clone https://github.com/Jagadeesh0463/signalnoise-ai.git
cd signalnoise-ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
cp .env.example .env   # add GROQ_API_KEY
streamlit run app/streamlit_app.py
```

## Docker

```bash
# Build
docker build -t signalnoise-ai .

# Run with env file
docker run -p 8501:8501 --env-file .env signalnoise-ai

# Or with docker-compose (recommended)
docker-compose up --build
```

Access at [http://localhost:8501](http://localhost:8501).

### Volumes

The `docker-compose.yml` mounts `./data/processed` as a volume so ChromaDB and SQLite persist across container restarts:

```yaml
volumes:
  - ./data/processed:/app/data/processed
```

## Streamlit Cloud

1. Fork the repository
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub account
4. Select `app/streamlit_app.py` as the entry point
5. Add secrets in Streamlit Cloud dashboard (Settings → Secrets):

```toml
GROQ_API_KEY = "gsk_..."
GROQ_MODEL = "llama3-8b-8192"
MIN_DOCS_FOR_BERTOPIC = "10"
MIN_TOPIC_SIZE = "2"
SPACY_MODEL = "en_core_web_sm"
```

**Note:** Streamlit Cloud does not persist files between restarts. ChromaDB and SQLite will reset. For persistent deployment, use a VM or container with mounted volumes.

## Production VM (Ubuntu)

```bash
# 1. Install dependencies
sudo apt update && sudo apt install -y python3-pip python3-venv git

# 2. Clone and set up
git clone https://github.com/Jagadeesh0463/signalnoise-ai.git
cd signalnoise-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 3. Configure
cp .env.example .env && nano .env

# 4. Run behind nginx with systemd

# /etc/systemd/system/signalnoise.service
[Unit]
Description=SignalNoise AI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/signalnoise-ai
Environment="PATH=/home/ubuntu/signalnoise-ai/.venv/bin"
ExecStart=/home/ubuntu/signalnoise-ai/.venv/bin/streamlit run app/streamlit_app.py --server.port 8501
Restart=always

[Install]
WantedBy=multi-user.target

sudo systemctl enable signalnoise && sudo systemctl start signalnoise
```

## Enterprise Deployment (Ollama, On-Premise)

Replace Groq with Ollama for a fully offline deployment:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3

# In .env:
GROQ_API_KEY=not-used
GROQ_MODEL=llama3
GROQ_BASE_URL=http://localhost:11434/v1
```

Update `narrator.py` to use `base_url` parameter if switching to the Ollama OpenAI-compatible endpoint.

## Resource Requirements

| Environment | CPU | RAM | Disk |
|-------------|-----|-----|------|
| Development | 2 cores | 4 GB | 5 GB |
| Production (small) | 4 cores | 8 GB | 20 GB |
| Production (large) | 8 cores | 16 GB | 50 GB |

The MiniLM model downloads ~80MB on first run. BERTopic and HDBSCAN run on CPU — no GPU required.

## Health Check

The Docker container includes a health check endpoint. For VM deployments, check the Streamlit process:

```bash
systemctl status signalnoise
curl -f http://localhost:8501/_stcore/health
```
