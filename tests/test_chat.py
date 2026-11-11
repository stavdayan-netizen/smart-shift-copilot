"""Integration tests: the API with the model replaced by a scripted fake."""
from app.agent import ModelEvent, run_turn
from app.tools import registry
from app.costs import Usage
from app.db import Message, Run, SessionLocal, User
from tests.conftest import read_sse


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_required_and_wrong_password(client):
    client.cookies.clear()
    assert client.get("/api/conversations").status_code == 401
    bad = client.post("/api/login", json={"name": "Eve", "code": "nope"})
    assert bad.status_code == 401
    assert client.post("/api/login", json={"name": "E", "code": "x"}).status_code == 422


def test_chat_streams_text_and_saves_once(client, db, logged_in, fake):
    fake.turns.append([
        ModelEvent(type="text", text="Shift coverage is "),
        ModelEvent(type="text", text="complete this week."),
        ModelEvent(type="stop", stop_reason="end_turn", usage=Usage(120, 18),
                   content=[{"type": "text", "text": "Shift coverage is complete this week."}]),
    ])
    r = client.post("/api/chat", json={"message": "Is the coverage complete?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = read_sse(r)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Shift coverage is complete this week."
    conv_id = events[0]["conversation_id"]
    msgs = db.query(Message).filter_by(conversation_id=conv_id).order_by(Message.id).all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].content == "Shift coverage is complete this week."
    run = db.query(Run).filter_by(conversation_id=conv_id).one()
    assert run.status == "ok" and run.input_tokens == 120 and run.output_tokens == 18
    assert events[-1]["cost_usd"] == 0.0  # fake model has no price table


def test_tool_loop_runs_a_registered_tool(client, db, logged_in, fake, monkeypatch):
    """The dispatch mechanism and the loop, with a throwaway test-only tool (no domain tools exist yet)."""
    calls = []
    monkeypatch.setattr(registry, "TOOLS", [{"name": "echo", "description": "test tool",
                                              "input_schema": {"type": "object", "properties": {"word": {"type": "string"}},
                                                               "required": ["word"], "additionalProperties": False}}])
    monkeypatch.setattr(registry, "HANDLERS", {"echo": lambda db_, inp, uid: calls.append(inp) or {"echoed": inp["word"]}})
    fake.turns.extend([
        [ModelEvent(type="stop", stop_reason="tool_use", usage=Usage(300, 40), content=[
            {"type": "tool_use", "id": "tu_1", "name": "echo", "input": {"word": "hi"}}])],
        [ModelEvent(type="text", text="Echoed hi."),
         ModelEvent(type="stop", stop_reason="end_turn", usage=Usage(420, 30), content=[{"type": "text", "text": "Echoed hi."}])],
    ])
    events = read_sse(client.post("/api/chat", json={"message": "echo hi"}))
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["status"] for t in tools] == ["start", "done"] and tools[0]["name"] == "echo"
    assert calls == [{"word": "hi"}]
    run = db.query(Run).filter_by(conversation_id=events[0]["conversation_id"]).one()
    assert run.tool_calls == 1 and run.tool_names == "echo" and run.input_tokens == 720  # both model calls summed


def test_unknown_tool_and_bad_input_return_errors_not_exceptions(client, db):
    import json

    assert "unknown tool" in json.loads(registry.execute("nope", {}, db))["error"]
    monkey = {"boom": lambda db_, inp, uid: 1 / 0}
    registry.HANDLERS.update(monkey)
    try:
        assert "ZeroDivisionError" in json.loads(registry.execute("boom", {}, db))["error"]
    finally:
        registry.HANDLERS.pop("boom")


def test_refusal_is_reported_not_hidden(client, db, logged_in, fake):
    fake.turns.append([ModelEvent(type="stop", stop_reason="refusal", usage=Usage(50, 0), content=[])])
    events = read_sse(client.post("/api/chat", json={"message": "do something odd"}))
    assert any(e["type"] == "text" and "אין לי אפשרות" in e["text"] for e in events)
    conv_id = events[0]["conversation_id"]
    assert db.query(Run).filter_by(conversation_id=conv_id).one().status == "refusal"


def test_dropped_connection_leaves_no_half_row(client, db, logged_in, fake):
    fake.turns.append([
        ModelEvent(type="text", text="This reply will be cut "),
        ModelEvent(type="text", text="in the middle."),
        ModelEvent(type="stop", stop_reason="end_turn", usage=Usage(10, 5), content=[{"type": "text", "text": "x"}]),
    ])
    with SessionLocal() as s:
        user = s.query(User).filter_by(name="boss").one()
        gen = run_turn(s, user=user, conversation=None, text="cut me off", client=fake)
        meta = next(gen)
        first = next(gen)
        assert meta["type"] == "meta" and first["type"] == "text"
        gen.close()  # the browser went away
        conv_id = meta["conversation_id"]
    roles = [m.role for m in db.query(Message).filter_by(conversation_id=conv_id).all()]
    assert roles == ["user"]  # the user's message is kept, no partial assistant row
    run = db.query(Run).filter_by(conversation_id=conv_id).one()
    assert run.status == "aborted"


def test_digest_endpoint_needs_secret(client, logged_in):
    assert client.post("/internal/digest").status_code == 401
    r = client.post("/internal/digest", headers={"X-Cron-Secret": "cron-test"})
    assert r.status_code == 200
    assert r.json()["text"].startswith("Smart Shift Copilot —")
    assert r.json()["sent"] is False


def test_system_prompt_has_no_unfilled_placeholders(client, db):
    from app import agent as agent_module

    text = agent_module.build_system(db)[0]["text"]
    assert "Smart Shift Copilot" in text and "{{" not in text
