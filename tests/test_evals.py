"""The eval runner's own plumbing, with the fake model: no network, no cost."""
from app.agent import FakeModelClient
from evals import run as evals_run


def test_case_history_reaches_the_model_as_earlier_turns(client):
    fake = FakeModelClient()
    case = {"id": "t", "input": "Is anyone free on Sunday?",
            "history": [{"role": "user", "content": "who submitted?"},
                        {"role": "assistant", "content": "Everyone except Noa submitted."}]}
    result = evals_run.run_case(case, fake)
    sent = fake.last_messages
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == "who submitted?"
    assert "Everyone except Noa" in sent[1]["content"]
    assert sent[2]["content"][-1]["text"] == "Is anyone free on Sunday?"
    assert result["status"] == "ok"


def test_case_without_history_is_a_single_turn(client):
    fake = FakeModelClient()
    evals_run.run_case({"id": "t", "input": "Who has not submitted?"}, fake)
    assert [m["role"] for m in fake.last_messages] == ["user"]
