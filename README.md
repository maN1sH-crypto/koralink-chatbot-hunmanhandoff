# KoraLink Human-Agent Chat V1

Working Flask + MongoDB + Socket.IO layer around the existing KoraLink chatbot.
It keeps `scap.answer_finder()` and its existing `answer/images/step_images` response.

## Install
`pip install -r requirements.txt`

Set environment variables:
`MONGODB_URI`, `MONGODB_DB=koralink`, `SECRET_KEY`, `FRONTEND_ORIGIN`.

Create an agent:
`python create_agent.py "Support Agent" agent@example.com "StrongPassword"`

Run:
`python app.py`

Agent dashboard:
`http://127.0.0.1:5000/agent`

Customer API:
`POST /api/customer/session`
`POST /api/customer/message`
`GET /api/customer/conversation/<id>?customer_id=<id>`

Agent API:
`POST /api/agent/login`
`GET /api/agent/queue`
`GET /api/agent/active`
`GET /api/agent/conversation/<id>`
`POST /api/agent/conversation/<id>/claim`
`POST /api/agent/conversation/<id>/message`
`POST /api/agent/conversation/<id>/close`

Conversation states: `bot_active`, `waiting_human`, `human_active`, `closed`.
When status is `waiting_human` or `human_active`, the backend does not call the AI.
Claim uses an atomic MongoDB update so two agents cannot claim the same waiting chat.

For production, use HTTPS, restrict CORS, rate-limit APIs, add stronger auth/session handling,
and deploy Socket.IO with a production server.
