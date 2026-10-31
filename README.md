# KoraLink Customer Support Chat

Flask chatbot, MongoDB-backed knowledge base, and live support dashboard for KoraLink.

## Start here

- **Client/local installation:** follow [SETUP_GUIDE.md](SETUP_GUIDE.md) from top to bottom.
- **Technical components and workflow:** see [tech.txt](tech.txt).
- **Secrets:** copy `.env.example` to `.env`; never commit or share `.env`.
- **Local service:** `python app.py`, then open `/`, `/agent`, or `/knowledge` on `http://127.0.0.1:5000`.
- **GitHub:** generated environments, local secrets, and `data/backups/` are excluded by `.gitignore`. Review `git status` before pushing.

The customer chat can be served by Flask or hosted separately as a static frontend. A separately hosted frontend must be configured with the HTTPS backend URL. The agent dashboard and knowledge editor are served by Flask.

## Main files

| File or folder | Purpose |
| --- | --- |
| `app.py` | Flask API, Socket.IO, customer and agent flows, dashboard routes, attachments. |
| `bot_work.py`, `scap.py`, `groq_client.py` | FAQ search/embeddings, answer selection, language handling, and LLM fallbacks. |
| `database.py` | Import/update the JSON knowledge source in MongoDB; full replacement is an explicit option. |
| `create_agent.py` | Create or update agent/admin credentials. |
| `index.html`, `static/widget.js` | Customer chat and website embed loader. |
| `templates/`, `static/agent.*` | Support dashboard and knowledge editor UI. |
| `koralink_new.json` | English source knowledge for initial import/update. |
| `data/question_embeddings.npy*` | Regenerable local FAQ embedding cache. |
| `customer_socket_example.js` | Optional Socket.IO integration example. |

## Message flow

The browser sends messages to Flask. Flask stores conversation history and state in MongoDB, searches active FAQ records with the local Sentence Transformer embeddings, and uses configured language-model providers when needed. Human handoff places a chat in the support queue; agent/customer updates use Socket.IO with polling fallback. See the setup guide for configuration and the technology document for more detail.

## Deployment note

The repository does not contain a live ngrok URL. Use a stable HTTPS backend domain for production; configure the static frontend's API URL and set `FRONTEND_ORIGIN` to the exact approved frontend domain. The built-in `python app.py` server is for development and demos; production needs a persistent host and a Flask-SocketIO-compatible server/runtime.



---

## Useful API routes

Customer: `POST /api/customer/session`, `POST /api/customer/message`, `GET /api/customer/conversation/<id>`.

Agent: `POST /api/agent/login`, `GET /api/agent/queue`, `GET /api/agent/active`, `GET /api/agent/conversation/<id>`, plus claim, message, close, and attachment routes under `/api/agent/conversation/<id>/...`.

## Routine maintenance

- Edit knowledge in the admin page and keep a separate approved JSON export/version when making major content changes.
- Keep `.env`, `venv/`, `.venv/`, `__pycache__/`, and `data/backups/` out of GitHub/client source archives. The embedding cache is included in this repository to avoid recomputing it on every clean setup; it can be regenerated if missing. Never send `.env`.
- Keep Mongo backups in `data/backups/` or a secure off-device backup service. Restrict access because backups may contain customer or knowledge data.
- Remove only generated files that can be recreated. Do not delete `koralink_new.json`, the active embedding cache, Mongo backups, or environment files without first checking what depends on them.
- For code changes, review `git status` before sharing or deploying so secrets and customer data are not included.
