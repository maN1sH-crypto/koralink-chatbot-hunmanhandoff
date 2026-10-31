# KoraLink Chatbot — Client Setup Guide

This guide sets up the Flask chatbot, MongoDB knowledge base, customer chat, and support dashboard on a Windows computer. It assumes a clean copy cloned from the project GitHub repository.

> Keep `.env` private. Never send it to the client, upload it to GitHub, or include it in a Netlify deployment. The repository contains `.env.example` only.

## What the client needs

- Windows 10/11 and Python 3.10 or newer.
- A MongoDB Atlas database (or another reachable MongoDB server).
- Valid API keys for Groq, Gemini, and OpenRouter. The current app initializes all three clients when it starts.
- Internet access on the first run so Sentence Transformers can download `all-MiniLM-L6-v2`.
- Access to the GitHub repository and permission to use the configured MongoDB database.

The model runs locally on the backend after download. It does not use Hugging Face inference credits. Translation and language-model answers still call the configured API providers and are subject to their quotas and pricing.

## 1. Clone the repository

Open PowerShell in the folder where you keep projects:

```powershell
git clone https://github.com/maN1sH-crypto/deshboard.git
cd deshboard
```

If the repository URL or default branch changes, use the URL supplied by the project owner. Confirm that `app.py`, `requirements.txt`, and `koralink_new.json` are in the current folder:

```powershell
Get-ChildItem app.py, requirements.txt, koralink_new.json
```

## 2. Create the Python environment

Run these commands from the folder containing `app.py`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `py -3` is not recognized, install Python from python.org, enable **Add Python to PATH**, reopen PowerShell, and use `python -m venv .venv` instead. If PowerShell blocks activation, use Command Prompt and run `.venv\Scripts\activate.bat`.

## 3. Prepare MongoDB

1. Create or select the client's MongoDB Atlas project and cluster.
2. Create a database user with access to the application database. The chatbot needs to read and write knowledge, agents, conversations, messages, and temporary chat attachments.
3. Add the backend computer's IP address to Atlas Network Access for setup. For production, allow only the backend host's required IP addresses.
4. Copy the MongoDB connection URI. URL-encode special characters in the password before putting it in the URI.

Do not give the client unrestricted database-owner access for normal use. Keep database access on the backend; browser code must never receive the MongoDB URI.

## 4. Configure environment variables

Create a private local `.env` file from the example:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set these values in `.env`:

```dotenv
MONGO_URI=mongodb+srv://DB_USER:DB_PASSWORD@YOUR_CLUSTER.mongodb.net/?retryWrites=true&w=majority
DATABASE_NAME=koralink
COLLECTION_NAME=knowledge
SECRET_KEY=PASTE_A_LONG_RANDOM_SECRET_HERE
FRONTEND_ORIGIN=http://127.0.0.1:5000,http://localhost:5000,http://127.0.0.1:5501,http://localhost:5501
PORT=5000
EMBEDDING_PROVIDER=local
EMBEDDING_DEVICE=cpu
GROQ_API_KEY=YOUR_GROQ_KEY
GEMINI_API_KEY=YOUR_GEMINI_KEY
OPENROUTER_API_KEY=YOUR_OPENROUTER_KEY
```

Generate a strong `SECRET_KEY` in PowerShell with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the result into `.env`. Replace every example value with the client's real configuration. All three language-provider keys are currently required for startup because the app initializes all three provider clients. Keep those keys only in the backend `.env` or the backend host's secret manager.

## 5. Load the knowledge base

Make sure `.env` points to the intended database and `koralink_new.json` is present. Then run:

```powershell
python database.py
```

This imports new knowledge and updates matching questions; it does not clear all existing knowledge. Do not run `python database.py --replace-knowledge` unless the client explicitly wants to replace the entire knowledge collection and has confirmed the target database. Replacement creates a backup first, but it still overwrites the collection.

## 6. Create the administrator and support logins

Create an admin account for the Knowledge Base page:

```powershell
python create_agent.py "Knowledge Admin" admin@client.example "REPLACE_WITH_A_UNIQUE_PASSWORD" admin
```

Create a support-agent login for the call-center dashboard:

```powershell
python create_agent.py "Support Agent" agent@client.example "REPLACE_WITH_A_DIFFERENT_PASSWORD" agent
```

Replace the sample email addresses and passwords. Use unique strong passwords and share them privately. Do not commit real credentials or paste them into this guide. Run the command again with the same email to update that account's password or role.

## 7. Start the app and sign in

With `.venv` activated, start Flask:

```powershell
python app.py
```

Wait for the local embedding model and FAQ records to load. On first run, model download and FAQ embedding creation can take several minutes. Keep this terminal open while using the app.

Open these pages on the same computer:

- Health check: `http://127.0.0.1:5000/health` — expect `ok: true` and `mongodb: connected`.
- Customer chatbot: `http://127.0.0.1:5000/`
- Support dashboard: `http://127.0.0.1:5000/agent`
- Knowledge manager: `http://127.0.0.1:5000/knowledge`

Log into `/agent` using an agent or admin account. Log into `/knowledge` using an admin account.

## 8. Connect a Netlify frontend for a demo

The checked-in frontend no longer points to a developer's temporary ngrok tunnel. When the client hosts `index.html` separately from Flask, provide the backend URL using either:

- A query parameter on the chat page: `https://CLIENT-SITE.netlify.app/?api=https://CLIENT-BACKEND.example.com`
- The widget's `data-api-url` setting, as shown below.

For a temporary demo, the backend can be exposed through ngrok. The Flask app and ngrok tunnel must remain running, and the tunnel URL can change. Do not treat an ngrok URL as a production address.

Set the backend `.env` `FRONTEND_ORIGIN` to the exact Netlify site origin, for example:

```dotenv
FRONTEND_ORIGIN=https://CLIENT-SITE.netlify.app
```

Restart Flask after changing `.env`. Do not add a trailing slash to the origin. If more than one trusted frontend is used, separate origins with commas.

For embedding on another website, the deployed files must keep `index.html` at the chat URL and `static/widget.js` at the widget script URL. Add this snippet to the website and replace the example domains:

```html
<script
  src="https://CLIENT-SITE.netlify.app/static/widget.js"
  data-chat-url="https://CLIENT-SITE.netlify.app/"
  data-api-url="https://CLIENT-BACKEND.example.com"
  defer
></script>
```

`data-chat-url` is the deployed chat page, and `data-api-url` is the Flask backend. Keep the directory layout intact. For Netlify, publish only the frontend files needed for the chat; never publish `.env`, the Python virtual environment, or private database backups.

## 9. Production deployment checklist

Before real customers use the system:

- Deploy Flask as a persistent HTTPS service on a backend host with enough memory for the local embedding model and support for the app's Flask-SocketIO/WebSocket traffic.
- Use a stable backend domain; update the frontend API URL and `FRONTEND_ORIGIN` to exact production domains.
- Put MongoDB and LLM credentials in the backend host's secret manager. Restrict MongoDB network access to the backend host.
- Configure a production server/runtime compatible with Flask-SocketIO; `python app.py` is for local development and demos.
- Verify login, knowledge answers, multilingual responses, multiple simultaneous chats, agent replies on a second device, attachments, chat closing, and attachment deletion.
- Set up database backups, monitoring, privacy/retention rules, and an operational owner before launch.

## Troubleshooting

| Symptom | First checks |
| --- | --- |
| Flask exits saying `MONGO_URI` is missing | Confirm `.env` exists beside `app.py` and the variable name/value is correct. |
| MongoDB server selection or timeout error | Check the URI, encoded password, Atlas database user, cluster status, and Network Access IP allowlist. |
| `401` or authentication error from an LLM provider | Confirm all three API keys are valid, enabled, and have available quota. |
| First startup appears paused while loading | Wait for the local model download and FAQ embedding generation to finish; later starts should reuse the cache. |
| `Database collection ... is empty` | Run `python database.py` against the intended database and confirm the collection name matches `COLLECTION_NAME`. |
| Browser says it cannot reach Flask | Confirm Flask is running, the frontend API URL is correct, HTTPS is used for hosted frontend/backend, and `FRONTEND_ORIGIN` exactly matches the frontend origin. |
| Dashboard works on laptop but not another device | The dashboard URL must use the reachable HTTPS backend host, not `127.0.0.1`; check tunnel/hosting, CORS, and Socket.IO/WebSocket support. |

## What belongs in GitHub

Commit the application source, `koralink_new.json`, `.env.example`, `requirements.txt`, and documentation. Do not commit `.env`, `.venv/` or `venv/`, `__pycache__/`, logs, or `data/backups/`. Keep the knowledge source JSON only if the client has approved sharing it in the repository.
