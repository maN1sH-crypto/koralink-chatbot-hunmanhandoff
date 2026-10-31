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

For client-facing monthly and implementation budget planning, use the estimates in the existing **Budget draft for a client proposal** section below and verify vendor pricing before quoting.

---
## Budget draft

This is a planning estimate in USD, not a vendor quote. Confirm provider prices, region, tax, storage, expected usage, and service limits before committing. Render publishes current compute plans and pricing on its [pricing page](https://render.com/pricing); a 1 CPU / 2 GB service is identified as `1c-2g` in its [compute plan documentation](https://render.com/docs/compute-plans). MongoDB Atlas lists M0 at $0, Flex at $8–$30/month, and dedicated clusters from $56.94/month on its [pricing page](https://www.mongodb.com/pricing). Netlify currently lists Free at $0, Personal at $9/month, and Pro starting at $20/month on its [pricing page](https://www.netlify.com/pricing/). Groq lists GPT-OSS 120B at $0.15 per million input tokens and $0.60 per million output tokens; LLM usage must be measured from real conversations ([model pricing](https://console.groq.com/docs/model/openai/gpt-oss-120b)).

### Monthly operating allowance

| Item | Pilot allowance | Small production allowance |
| --- | ---: | ---: |
| Backend hosting | $25–$50 | $25–$50 |
| MongoDB Atlas | $0–$30 (M0/Flex; confirm storage/limits) | $8–$57+ (Flex or dedicated, depending on workload) |
| Netlify frontend | $0–$9 | $0–$20+ |
| LLM usage | $10–$30 initial budget cap; adjust after measurement | $20–$100+ based on volume, language, model, and fallback use |
| Domain and optional monitoring | $1–$10 | $5–$25 |
| **Planning total** | **about $36–$129/month** | **about $58–$252+/month** |

These totals are allowances, not guaranteed bills. The local embedding model itself has no per-request hosted inference fee, but it uses backend CPU/RAM. AI translation/answer generation has separate usage charges and quota limits. Chat uploads and stored conversations grow MongoDB usage. Add a monthly spending alert/cap where each vendor supports it and review actual usage after the first month. Prices exclude tax and currency conversion; quote the client in the agreed billing currency.

### One-time implementation and handover estimate

For the remaining production deployment and handover work, a proposal can use **$2,000–$4,000 one-time**, with final price set after confirming the items below. This is a suggested project quote, not an industry benchmark or a promise that all work is complete. It assumes the existing code and core features remain in scope, one production environment, limited client acceptance rounds, and no major redesign or new feature set.

- Production backend hosting, domain/CORS configuration, environment setup, and stable frontend connection.
- Production database configuration, knowledge import/review, backup and restore runbook.
- Security and reliability hardening appropriate to the agreed scope, including agent access, upload limits, error handling, and monitoring setup.
- End-to-end client acceptance session for chatbot, multilingual questions, multiple agents/customers, live replies, close/reopen flow, and attachments.
- README/runbook, admin and agent handover, and a short training session.

Suggested billing milestones: 40% at approved scope and kickoff, 40% when staging deployment is ready for client acceptance, and 20% after accepted production handover. Ongoing maintenance/support should be a separate monthly agreement (for example, define included hours, response times, and out-of-scope work explicitly). Do not promise uptime, compliance, unlimited AI usage, or unlimited support without the corresponding paid services and written scope.

## Useful API routes

Customer: `POST /api/customer/session`, `POST /api/customer/message`, `GET /api/customer/conversation/<id>`.

Agent: `POST /api/agent/login`, `GET /api/agent/queue`, `GET /api/agent/active`, `GET /api/agent/conversation/<id>`, plus claim, message, close, and attachment routes under `/api/agent/conversation/<id>/...`.

## Routine maintenance

- Edit knowledge in the admin page and keep a separate approved JSON export/version when making major content changes.
- Keep `.env`, `venv/`, `.venv/`, `__pycache__/`, and `data/backups/` out of GitHub/client source archives. The embedding cache is included in this repository to avoid recomputing it on every clean setup; it can be regenerated if missing. Never send `.env`.
- Keep Mongo backups in `data/backups/` or a secure off-device backup service. Restrict access because backups may contain customer or knowledge data.
- Remove only generated files that can be recreated. Do not delete `koralink_new.json`, the active embedding cache, Mongo backups, or environment files without first checking what depends on them.
- For code changes, review `git status` before sharing or deploying so secrets and customer data are not included.
