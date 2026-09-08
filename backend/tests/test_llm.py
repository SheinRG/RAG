"""Prompt construction and the streaming Q&A pipeline."""

import json

import pytest

import llm


def test_context_is_labelled_with_its_source_document():
    prompt = llm.build_system_prompt(
        [
            {"source": "Thesis.pdf", "content": "Chapter one."},
            {"source": "Notes.md", "content": "A remark."},
        ]
    )
    assert "[SOURCE: Thesis.pdf]" in prompt
    assert "[SOURCE: Notes.md]" in prompt
    assert "--- CONTEXT START ---" in prompt
    assert "--- CONTEXT END ---" in prompt


def test_empty_retrieval_still_produces_a_usable_prompt():
    prompt = llm.build_system_prompt([])
    assert "No document context available." in prompt


# ── Streaming ──


class FakeDelta:
    def __init__(self, content):
        self.content = content


class FakeStream:
    def __init__(self, tokens):
        self._tokens = tokens

    def __aiter__(self):
        async def gen():
            for t in self._tokens:
                yield type("C", (), {"choices": [type("Ch", (), {"delta": FakeDelta(t)})()]})()

        return gen()


class FakeCompletions:
    def __init__(self, tokens):
        self._tokens = tokens
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeStream(self._tokens)
        # The follow-up-suggestions call.
        message = type("M", (), {"content": json.dumps({"questions": ["A?", "B?", "C?"]})})()
        return type("R", (), {"choices": [type("Ch", (), {"message": message})()]})()


@pytest.fixture
def fake_groq(monkeypatch):
    completions = FakeCompletions(["Hello", " world"])
    monkeypatch.setattr(
        llm,
        "client",
        type("C", (), {"chat": type("Chat", (), {"completions": completions})()})(),
    )
    return completions


async def collect(agen):
    events = []
    async for raw in agen:
        for line in raw.strip().splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_stream_emits_tokens_sources_and_done(monkeypatch, fake_groq):
    monkeypatch.setattr(
        llm,
        "retrieve",
        lambda *a, **k: [{"source": "A.pdf", "content": "ctx", "document_id": "d1", "similarity": 0.9}],
    )

    events = await collect(llm.ask_stream("What is this?", "user-1"))
    kinds = [e["type"] for e in events]

    assert "".join(e["content"] for e in events if e["type"] == "token") == "Hello world"
    assert kinds.index("sources") < kinds.index("done")
    assert kinds[-1] == "done"
    sources = next(e for e in events if e["type"] == "sources")["content"]
    assert sources == [{"name": "A.pdf", "chunks": ["ctx"]}]


@pytest.mark.asyncio
async def test_retrieval_runs_off_the_event_loop(monkeypatch, fake_groq):
    """
    retrieve() does blocking network I/O with multi-second timeouts and a
    sleeping retry ladder. Calling it inline would freeze every other request
    sharing this worker, so it must go through the threadpool.
    """
    dispatched = []

    async def fake_threadpool(fn, *args, **kwargs):
        dispatched.append(fn)
        return []

    monkeypatch.setattr(llm, "run_in_threadpool", fake_threadpool)
    monkeypatch.setattr(llm, "retrieve", lambda *a, **k: pytest.fail("retrieve called inline"))

    await collect(llm.ask_stream("q", "user-1"))

    assert dispatched == [llm.retrieve]


@pytest.mark.asyncio
async def test_history_is_trimmed_to_the_configured_window(monkeypatch, fake_groq):
    monkeypatch.setattr(llm, "retrieve", lambda *a, **k: [])
    history = [{"role": "user", "content": f"m{i}"} for i in range(30)]

    await collect(llm.ask_stream("q", "user-1", history=history))

    messages = fake_groq.calls[0]["messages"]
    # system prompt + trimmed history + the new question
    assert len(messages) == llm.MAX_HISTORY_MESSAGES + 2
    assert messages[0]["role"] == "system"
    assert messages[-1]["content"] == "q"


@pytest.mark.asyncio
async def test_upstream_failure_reports_an_error_then_done(monkeypatch):
    monkeypatch.setattr(llm, "retrieve", lambda *a, **k: [])

    class Boom:
        async def create(self, **kwargs):
            raise RuntimeError("groq exploded: key=sk-secret")

    monkeypatch.setattr(
        llm, "client", type("C", (), {"chat": type("Chat", (), {"completions": Boom()})()})()
    )

    events = await collect(llm.ask_stream("q", "user-1"))
    error = next(e for e in events if e["type"] == "error")

    # The upstream message may carry internal detail; it must not reach the client.
    assert "sk-secret" not in error["content"]
    assert events[-1]["type"] == "done"
