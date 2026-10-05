"""Genie Conversation API proxy for catalog-wide natural-language Q&A.

Uses the app's WorkspaceClient (service principal in prod, CLI profile locally),
the same auth path as the Lakebase credential call in config.py.
"""
import os
import time

from . import config

GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "")  # set in app.yaml

# Genie can take 15-60s; poll with a generous ceiling.
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 110.0
MAX_RESULT_ROWS = 50


def _api():
    return config.get_workspace_client().api_client


def _poll_message(conversation_id: str, message_id: str) -> dict:
    api = _api()
    deadline = time.time() + POLL_TIMEOUT
    base = f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}/conversations/{conversation_id}/messages/{message_id}"
    while True:
        msg = api.do("GET", base)
        status = msg.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
            return msg
        if time.time() > deadline:
            msg["_timed_out"] = True
            return msg
        time.sleep(POLL_INTERVAL)


def _fetch_rows(conversation_id: str, message_id: str, attachment_id: str) -> dict:
    api = _api()
    path = (
        f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}/conversations/{conversation_id}"
        f"/messages/{message_id}/attachments/{attachment_id}/query-result"
    )
    try:
        res = api.do("GET", path)
        sr = res.get("statement_response", {})
        cols = [c["name"] for c in sr.get("manifest", {}).get("schema", {}).get("columns", [])]
        data = sr.get("result", {}).get("data_array", []) or []
        return {"columns": cols, "rows": data[:MAX_RESULT_ROWS]}
    except Exception:
        return {"columns": [], "rows": []}


def ask(question: str, conversation_id: str | None = None) -> dict:
    """Ask Genie a question. Blocking; call via asyncio.to_thread."""
    api = _api()

    if conversation_id:
        start = api.do(
            "POST",
            f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}/conversations/{conversation_id}/messages",
            body={"content": question},
        )
        message_id = start.get("message_id") or start.get("id")
    else:
        start = api.do(
            "POST",
            f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}/start-conversation",
            body={"content": question},
        )
        conversation_id = start.get("conversation_id")
        message_id = start.get("message_id") or start.get("id")

    msg = _poll_message(conversation_id, message_id)

    answer, sql, sql_description, attachment_id = None, None, None, None
    for att in msg.get("attachments", []) or []:
        if "text" in att and att["text"].get("content"):
            answer = att["text"]["content"]
        if "query" in att:
            q = att["query"]
            sql = q.get("query")
            sql_description = q.get("description")
            attachment_id = att.get("attachment_id")

    result = {"columns": [], "rows": []}
    if attachment_id and not msg.get("_timed_out"):
        result = _fetch_rows(conversation_id, message_id, attachment_id)

    status = msg.get("status")
    if msg.get("_timed_out"):
        error = "Genie is still working on this question (timed out waiting for a result). Try again."
    elif status == "FAILED":
        error = msg.get("error", {}).get("message") if isinstance(msg.get("error"), dict) else "Genie could not answer this question."
    else:
        error = None

    if not answer and sql_description:
        answer = sql_description

    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "status": status,
        "answer": answer,
        "sql": sql,
        "columns": result["columns"],
        "rows": result["rows"],
        "error": error,
    }
