# AI Interview Bot

An AI-powered technical interview platform that conducts, evaluates, and scores candidate interviews in real time. Text-based interviews are fully functional; a real-time voice pipeline (Deepgram STT + Claude LLM + ElevenLabs TTS) is in progress.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Frontend | Next.js 14 (App Router), React 18, Tailwind CSS |
| LLM | Anthropic Claude (claude-haiku-4-5) |
| Session State | Redis 7 (single source of truth, 4h TTL) |
| Database | PostgreSQL 16 (provisioned, not actively used) |
| Voice STT | Deepgram (streaming WebSocket) |
| Voice TTS | ElevenLabs (streaming) |

## Architecture

```
Browser (Next.js)
    │
    ├── REST ──► FastAPI ──► Claude LLM ──► Structured XML response
    │               │
    │               ├── Redis (session state)
    │               └── Question Bank (questions.json)
    │
    └── WebSocket ──► voice_ws_router
                        ├── Deepgram STT (streaming)
                        ├── Claude LLM (evaluation)
                        └── ElevenLabs TTS (streaming)
```

**State machine** (forward-only): `IDLE → STARTED → QUESTIONING → EVALUATING → COMPLETE`

**Text interview flow:**
1. `POST /api/v1/interview/start` — create session, select questions, return first question
2. `POST /api/v1/interview/answer` — evaluate via LLM, advance state, return next question
3. `GET /api/v1/interview/report/{session_id}` — full evaluation report with transcript

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** and npm
- **Docker** and Docker Compose (for Redis and PostgreSQL)
- **Anthropic API key** (required)
- Deepgram API key (optional — voice pipeline only)
- ElevenLabs API key (optional — voice pipeline only)

## Getting Started

### 1. Clone the repository

```bash
git clone <repo-url>
cd ai-interview-bot
```

### 2. Start infrastructure

```bash
docker-compose up -d
```

This starts Redis (port 6379) and PostgreSQL (port 5432).

### 3. Configure environment variables

**Backend** — copy the example and fill in your keys:

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...    # Required
DEEPGRAM_API_KEY=               # Optional (voice only)
ELEVENLABS_API_KEY=             # Optional (voice only)
REDIS_URL=redis://localhost:6379/0
ADMIN_API_KEY=change-me-admin-key
```

**Frontend** — copy the example:

```bash
cp frontend/.env.local.example frontend/.env.local
```

Edit `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
NEXT_PUBLIC_ADMIN_PASSPHRASE=admin
NEXT_PUBLIC_ADMIN_API_KEY=change-me-admin-key
```

### 4. Install dependencies

```bash
npm run setup
```

This creates a Python virtual environment, installs backend requirements, and runs `npm install` for the frontend.

Or install individually:

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

# Frontend
cd frontend
npm install
```

### 5. Run the application

```bash
npm run dev
```

This starts both services concurrently:
- **Backend:** http://localhost:8000
- **Frontend:** http://localhost:3000

Or run them separately:

```bash
npm run dev:backend    # Backend only
npm run dev:frontend   # Frontend only
```

### 6. Open the app

Navigate to http://localhost:3000. Sign in as a **Candidate** to take an interview, or as **Admin** (default passphrase: `admin`) to view session history and analysis.

## Project Structure

```
├── backend/
│   ├── main.py                          # FastAPI app entrypoint
│   ├── requirements.txt
│   ├── .env.example
│   ├── data/
│   │   └── questions.json               # Question bank
│   └── src/
│       ├── lib/
│       │   ├── anthropic_client.py       # LLM integration
│       │   └── settings.py              # App configuration
│       ├── prompts/
│       │   └── system_prompt.txt         # LLM system prompt
│       ├── routes/
│       │   ├── admin.py                  # Admin API endpoints
│       │   ├── voice_api.py              # Voice REST endpoints
│       │   └── voice_ws.py              # Voice WebSocket handler
│       └── services/
│           └── interview/
│               └── state_machine.py      # Interview state machine
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx                  # Home page
│   │   │   ├── login/page.tsx            # Login page
│   │   │   ├── interview/               # Interview pages
│   │   │   ├── report/                  # Report pages
│   │   │   └── admin/                   # Admin panel
│   │   ├── components/                  # Shared UI components
│   │   ├── contexts/AuthContext.tsx      # Auth state management
│   │   ├── lib/websocket.ts             # WebSocket client (voice)
│   │   └── services/
│   │       ├── api.ts                    # REST API client
│   │       └── admin-api.ts             # Admin API client
│   └── .env.local.example
├── docker-compose.yml                    # Redis + PostgreSQL
└── package.json                          # Root scripts (dev, setup)
```

## API Endpoints

### Interview

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/interview/start` | Start a new interview session |
| POST | `/api/v1/interview/answer` | Submit an answer and get the next question |
| GET | `/api/v1/interview/report/{session_id}` | Get the full evaluation report |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/admin/sessions` | List all interview sessions |
| GET | `/api/v1/admin/sessions/{session_id}` | Get session details and analysis |

### Voice (in progress)

| Method | Endpoint | Description |
|--------|----------|-------------|
| WebSocket | `/api/v1/voice/ws/{session_id}` | Bidirectional audio stream |
| POST | `/api/v1/voice/start` | Start a voice session |

## Development Notes

- **Session state** is stored exclusively in Redis. No in-memory caching across requests.
- **Question selection** uses weighted-random scoring based on role keywords, skill tags, and experience level.
- **LLM responses** are structured XML, parsed deterministically. `spoken_text` is candidate-facing; `internal_notes` and `score_update` are internal only.
- The **voice pipeline** is wired but incomplete. WebSocket routes are registered and the frontend client is scaffolded.

## License

Private — not licensed for redistribution.
