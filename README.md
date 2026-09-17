# Alectra Green Button Energy Dashboard ⚡

A modern, self-hosted energy analytics dashboard and automated scraper for **Alectra Utilities** customers. Built with FastAPI, SQLite, Playwright, and ApexCharts, packaged into a lightweight, memory-efficient Docker container.

Visualize your 15-minute smart meter intervals, track Time-of-Use (TOU) and Tiered electricity costs, monitor net grid balance (solar import vs. export), and integrate directly with AI assistants via the **Model Context Protocol (MCP)**.

---

## ✨ Features

- **Automated Daily Scraping**: Built-in headless Playwright bot that logs into the Alectra Green Button portal on a configurable schedule (e.g., daily at 06:00 AM) and automatically downloads your latest energy usage XML.
- **Manual XML Import**: Drag-and-drop any standard Green Button XML file directly into the web UI for instant parsing and archiving.
- **Dynamic Granularity & 15-Minute Drill-Down**:
  - **Auto-Switching View**: Displays Daily rollups for multi-week/monthly spans, Hourly for 1–2 weeks, and 15-minute resolution for 1–2 days.
  - **Zoom & Click Drill-Down**: Drag a zoom box over a single day on the 30-day chart or click any daily bar to instantly roll down to granular 15-minute interval profiles (up to 96 bars/day) with one-click zoom reset.
- **Ontario Time-of-Use (TOU) & Tier Breakdown**:
  - Automatically color-codes intervals by On-Peak, Mid-Peak, Off-Peak, and Ultra-Low Overnight (ULO) periods or Consumption Tiers.
  - Interactive tooltips showing breakdown, total import, and net balance on hover.
  - Dedicated breakdown summary card with totals.
- **Lightweight & Self-Host Ready**:
  - Strict **< 500 MB RAM** footprint.
  - SQLite with Write-Ahead Logging (WAL) and C-level query aggregation for instant loading across years of data.
  - No external database or cloud subscription required.
- **AI Assistant Integration (MCP Server)**:
  - Built-in Model Context Protocol (MCP) server over SSE (`/sse`) and Stdio (`mcp_server.py`).
  - Allows AI assistants (Claude Desktop, Cursor, Antigravity, ChatGPT) to answer questions about your energy usage, peak demand, and billing trends.

---

---

## 🚀 Deployment Options

### Option 1: Deploy with Pre-built Image (Container Registry)

If you don't want to build from source, you can deploy immediately on any Docker host (NAS, Synology, Unraid, Raspberry Pi, VPS) using only a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  dashboard:
    image: ghcr.io/yourusername/alectra-dashboard:latest
    container_name: alectra_usage_dashboard
    ports:
      - "8080:8000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=America/Toronto
      - ACCOUNT_NAME=John Doe
      - ACCOUNT_NUMBER=123456789
      - PHONE_NUMBER=905-555-1234
      - METER_NUMBER=
      - SCRAPE_ON_STARTUP=false
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 500M
```

Run:
```bash
docker compose pull
docker compose up -d
```

Or deploy as a single `docker run` command:
```bash
docker run -d \
  --name alectra_dashboard \
  -p 8080:8000 \
  -v $(pwd)/data:/app/data \
  -e TZ=America/Toronto \
  -e ACCOUNT_NAME="John Doe" \
  -e ACCOUNT_NUMBER="123456789" \
  -e PHONE_NUMBER="905-555-1234" \
  --memory=500m \
  --restart unless-stopped \
  ghcr.io/yourusername/alectra-dashboard:latest
```

---

### Option 2: Build & Run from Source (Docker Compose)

#### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/alectra-usage-dashboard.git
cd alectra-usage-dashboard
```

#### 2. Configure Environment Variables
```bash
cp .env.example .env
```
Edit `.env` (or `docker-compose.yml`) with your Alectra portal credentials.

#### 3. Build & Start the Container
```bash
docker compose up -d --build
```

Access the dashboard at `http://localhost:8080`.

---

## 📦 Building & Publishing to a Container Registry

### A. Automated via GitHub Actions (Recommended)
This repository includes `.github/workflows/docker-publish.yml`. When you push your code to GitHub:
1. GitHub Actions automatically builds the Docker image.
2. The image is published directly to **GitHub Container Registry** (`ghcr.io/<your-username>/<repo-name>:latest`).
3. You can set the package to **Public** in GitHub under `Packages` so any server or NAS can pull it without logging in.

### B. Manual Build & Push (Docker Hub / GHCR)

To manually build and push to Docker Hub:
```bash
# 1. Log in to Docker Hub
docker login

# 2. Build the image
docker build -t yourusername/alectra-dashboard:latest .

# 3. Push to registry
docker push yourusername/alectra-dashboard:latest
```

To manually push to GitHub Container Registry:
```bash
# 1. Log in to GHCR with a Personal Access Token (PAT with write:packages)
echo $CR_PAT | docker login ghcr.io -u yourusername --password-stdin

# 2. Build and tag
docker build -t ghcr.io/yourusername/alectra-dashboard:latest .

# 3. Push
docker push ghcr.io/yourusername/alectra-dashboard:latest
```

---

## ⚙️ Configuration Reference

### Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `ACCOUNT_NAME` | Primary account holder name as registered with Alectra Utilities. | *(Required for scraper)* |
| `ACCOUNT_NUMBER` | Your Alectra account number. | *(Required for scraper)* |
| `PHONE_NUMBER` | Phone number associated with your Alectra account for verification. | *(Required for scraper)* |
| `METER_NUMBER` | Specific meter number if your account has multiple meters. | `""` (First meter) |
| `LOGIN_PORTAL_URL` | Alectra Green Button portal authentication URL. | `https://alectrautilitiesgbportal.savagedata.com/Connect/Authorize` |
| `TZ` | Timezone for scheduled scrapes and interval conversions. | `America/Toronto` |
| `SCRAPE_ON_STARTUP`| Trigger an immediate scrape when the container starts. | `false` |
| `DATABASE_PATH` | Path to SQLite database file. | `green_button.db` |
| `SCAN_FOLDER_PATH` | Directory where downloaded/uploaded XML files are processed. | `/app/data` |

### In-App Settings Modal
Click the **Settings (⚙️)** button in the top navigation bar to configure runtime parameters without restarting the container:
- **Scan Interval**: How frequently the background service checks `/app/data` for new XML files (default: `60 minutes`).
- **Archive Retention**: How many days to keep processed XML files in `/app/data/archive` before cleanup (default: `60 days`).
- **Green Button Time-Shift**: Allows manual hourly UTC offset adjustment if your utility provider exports interval data in UTC face values.
- **Scheduled Scrape Run Time**: Time of day (HH:MM in 24h format) for the automated daily scrape.
- **Wipe & Re-import**: Clears the SQLite database and re-processes all XML files from the archive directory.

---

## 🤖 AI Integration (Model Context Protocol / MCP)

The dashboard includes a full **Model Context Protocol (MCP)** server enabling AI tools to inspect your energy metrics.

### Exposed MCP Tools:
1. `get_energy_summary(date_range, resolution)`: Retrieves consumption, production, and cost totals for any timeframe.
2. `get_rate_breakdown(date_range)`: Returns breakdown by On-Peak, Mid-Peak, Off-Peak, ULO, and Tiers.
3. `get_peak_demand(date_range)`: Finds the highest 15-minute peak demand (kW) interval.
4. `get_system_status()`: Checks database status, last sync, and scraper logs.
5. `trigger_sync()`: Schedules a scan of the import directory.

### Antigravity IDE Configuration
Add the server to your project's `.agents/mcp_config.json` (or global `~/.gemini/config/mcp_config.json`):

```json
{
  "mcpServers": {
    "alectra-energy": {
      "serverUrl": "http://localhost:8080/sse"
    }
  }
}
```

Or for direct local stdio execution:
```json
{
  "mcpServers": {
    "alectra-energy": {
      "command": "python",
      "args": ["${workspaceFolder}/mcp_server.py"],
      "env": {
        "DATABASE_PATH": "${workspaceFolder}/green_button.db"
      }
    }
  }
}
```

### Claude Desktop Configuration
Add the following to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "alectra-dashboard": {
      "command": "python",
      "args": ["/path/to/alectra_usage_dashboard/mcp_server.py"],
      "env": {
        "DATABASE_PATH": "/path/to/alectra_usage_dashboard/green_button.db"
      }
    }
  }
}
```

### Home Assistant Integration

You can integrate your dashboard with **Home Assistant** in two powerful ways:

#### Option A: Home Assistant Assist (Voice & Chat LLM via MCP)
If you use Home Assistant Assist with an LLM (such as **Extended OpenAI Conversation**, **Local Ollama**, or the **Home Assistant MCP Client** integration):
1. In Home Assistant, open your LLM conversation agent settings or MCP client configuration.
2. Add a new **SSE MCP Server**:
   - **Name**: `Alectra Energy`
   - **Server URL**: `http://<YOUR_DOCKER_HOST_IP>:8080/sse`
   - **Transport**: `SSE (Server-Sent Events)`
3. Enable the exposed tools (`get_energy_summary`, `get_rate_breakdown`, `get_peak_demand`, `get_system_status`).
4. You can now ask Assist via voice or text:
   - *"How much electricity did we use yesterday?"*
   - *"What was our highest peak demand this week?"*
   - *"Give me a breakdown of our On-Peak vs Off-Peak electricity cost."*

#### Option B: Home Assistant REST Sensor (Native Dashboard Entities)
To pull your latest Alectra usage and costs into Home Assistant entity cards or automations, add the following to your `configuration.yaml`:

```yaml
sensor:
  - platform: rest
    name: "Alectra Energy Latest Day"
    resource: "http://<YOUR_DOCKER_HOST_IP>:8080/api/data?date_range=latest_day&resolution=1d"
    scan_interval: 3600 # Check every hour
    value_template: "{{ value_json.consumption[0][1] | round(2) if value_json.consumption | length > 0 else 0 }}"
    unit_of_measurement: "kWh"
    device_class: energy
    state_class: total
    json_attributes_path: "$.tou_summary"
    json_attributes:
      - on_peak_kwh
      - mid_peak_kwh
      - off_peak_kwh
      - ulo_kwh
      - on_peak_cost
      - mid_peak_cost
      - off_peak_cost
      - ulo_cost

  - platform: rest
    name: "Alectra Energy Latest Day Cost"
    resource: "http://<YOUR_DOCKER_HOST_IP>:8080/api/data?date_range=latest_day&resolution=1d"
    scan_interval: 3600
    value_template: "{{ value_json.consumption_cost[0][1] | round(2) if value_json.consumption_cost | length > 0 else 0 }}"
    unit_of_measurement: "$"
    device_class: monetary
```

### Generic SSE Transport (Cursor / Web LLM Clients)
Connect any MCP client supporting HTTP Server-Sent Events to:
```
http://<YOUR_DOCKER_HOST_IP>:8080/sse
```

---

## 🛠️ Local Development (Without Docker)

### Prerequisites
- Python 3.10+
- Node.js (optional, only for linting)
- Playwright Chromium browser

### Setup
```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 3. Start the application
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000` in your browser.

---

## 🔒 Security & Privacy

- **100% Local & Self-Hosted**: All meter readings, timestamps, and cost data remain inside your local SQLite database or Docker volume. No external analytics, telemetry, or third-party servers are contacted.
- **Credentials Handling**: Scraper credentials are read strictly from environment variables and never logged or exposed via API endpoints.
- **Git Ready**: A pre-configured `.gitignore` ensures that database files (`*.db`), downloaded XML files (`data/`), Python bytecode (`__pycache__/`), and credentials files (`.env`) are never committed to version control.

---

## 📄 License

This project is licensed under the **MIT License**. You are free to modify, distribute, and self-host for personal or commercial use.
