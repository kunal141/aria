"""
Teams FastAPI Adapter — Week 13

Single endpoint that receives all Teams activities and dispatches to ARIAActivityHandler.

Run:
  uv run uvicorn aria.integrations.teams_adapter:app --host 0.0.0.0 --port 3978

Local dev (ngrok):
  ngrok http 3978
  → Set messaging endpoint in Azure Bot: https://<ngrok-id>.ngrok.io/api/messages

Required env vars:
  TEAMS_APP_ID       — from Azure Bot resource
  TEAMS_APP_PASSWORD — from Azure Bot resource
"""
import os
from aiohttp import web
from aiohttp.web import Request, Response

from botbuilder.core import BotFrameworkAdapterSettings, BotFrameworkAdapter
from botbuilder.schema import Activity

from aria.integrations.teams_bot import ARIAActivityHandler

# Adapter — verifies requests come from Microsoft
_SETTINGS = BotFrameworkAdapterSettings(
    app_id=os.getenv("TEAMS_APP_ID", ""),
    app_password=os.getenv("TEAMS_APP_PASSWORD", ""),
)
_ADAPTER = BotFrameworkAdapter(_SETTINGS)
_BOT     = ARIAActivityHandler()


async def messages(req: Request) -> Response:
    """Receive all incoming Teams activity."""
    if req.content_type != "application/json":
        return Response(status=415)

    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    response = await _ADAPTER.process_activity(activity, auth_header, _BOT.on_turn)
    if response:
        return Response(
            status=response.status,
            body=response.body,
            content_type="application/json",
        )
    return Response(status=201)


app = web.Application()
app.router.add_post("/api/messages", messages)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=3978)
