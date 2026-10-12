"""Claude access and the Claude extraction engine, verified with fake clients (no network, no API key)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from kgdemo import config, llm
from kgdemo.extract_llm import ClaudeExtractor, extraction_schema, system_prompt, user_message
from kgdemo.extraction import extract_all, extract_record
from kgdemo.llm import LLMError, LLMRefusal, LLMUnavailable, structured_call, text_call
from kgdemo.ontology import load_ontology

from test_extraction import HERO_DOC, HERO_MEETING, HERO_TEXT, hero_record

FORBIDDEN = {"thinking", "temperature", "top_p", "top_k", "tool_choice", "tools", "budget_tokens", "output_format"}


# ---------------------------------------------------------------------------- fakes
def response(payload=None, *, stop_reason: str = "end_turn", content=None, stop_details=None):
    if content is None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(stop_reason=stop_reason, stop_details=stop_details, content=content)


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeClient:
    """Stands in for anthropic.Anthropic: records every beta.messages.create call."""

    def __init__(self, result):
        self.beta = SimpleNamespace(messages=FakeMessages(result))

    @property
    def calls(self) -> list[dict]:
        return self.beta.messages.calls


def _http_response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


def hero_payload(**overrides) -> dict:
    payload = {
        "meeting": {"records_meeting": True, "title": "Investment Committee Meeting", "date": "2026-01-15",
                    "meeting_type": "Investment Committee"},
        "entities": [
            {"ref": "PER-001", "label": "Person", "name": "Douglas Whitfield", "mentions": ["Douglas Whitfield"]},
            {"ref": "PER-002", "label": "Person", "name": "Meredith Calloway", "mentions": ["Meredith Calloway"]},
            {"ref": "MEETING", "label": "Meeting", "name": "Investment Committee Meeting", "mentions": []},
            {"ref": "COM-IC", "label": "Committee", "name": "Investment Committee",
             "mentions": ["Investment Committee"]},
            {"ref": "CMP-NVDA", "label": "Company", "name": "Nvidia", "mentions": ["Nvidia"]},
            {"ref": "THM-AI", "label": "Theme", "name": "AI Infrastructure", "mentions": ["AI infrastructure"]},
            {"ref": "CON-GPU", "label": "Concept", "name": "GPU Capacity", "mentions": ["GPU capacity"]},
        ],
        "relationships": [
            {"source": "DOCUMENT", "type": "RECORDS", "target": "MEETING", "evidence": "Investment Committee Meeting"},
            {"source": "PER-001", "type": "ATTENDED", "target": "MEETING", "evidence": "Participants: Douglas Whitfield"},
            {"source": "PER-002", "type": "ATTENDED", "target": "MEETING", "evidence": "Participants: Meredith Calloway"},
            {"source": "MEETING", "type": "HELD_BY", "target": "COM-IC", "evidence": "Investment Committee Meeting"},
            {"source": "MEETING", "type": "DISCUSSED", "target": "CMP-NVDA",
             "evidence": "We remain bullish on Nvidia and other AI infrastructure providers."},
            {"source": "MEETING", "type": "DISCUSSED", "target": "THM-AI",
             "evidence": "We remain bullish on Nvidia and other AI infrastructure providers."},
            {"source": "MEETING", "type": "DISCUSSED", "target": "CON-GPU",
             "evidence": "The technology team believes demand for GPU capacity will continue through 2027."},
            {"source": "DOCUMENT", "type": "MENTIONS", "target": "CMP-NVDA",
             "evidence": "We remain bullish on Nvidia and other AI infrastructure providers."},
            {"source": "DOCUMENT", "type": "MENTIONS", "target": "THM-AI",
             "evidence": "We remain bullish on Nvidia and other AI infrastructure providers."},
            {"source": "DOCUMENT", "type": "MENTIONS", "target": "CON-GPU",
             "evidence": "The technology team believes demand for GPU capacity will continue through 2027."},
        ],
    }
    payload.update(overrides)
    return payload


def _graph(ex):
    return ({e.key for e in ex.entities},
            {(r.source, r.type, r.target, tuple(sorted(r.properties.items()))) for r in ex.relationships})


@pytest.fixture
def no_credentials(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "KG_LLM_DISABLED"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------- request shape
def test_structured_call_request_shape():
    schema = extraction_schema()
    client = FakeClient(response({"ok": True}))
    assert structured_call("SYSTEM", "USER", schema, effort="low", client=client) == {"ok": True}
    (kwargs,) = client.calls
    assert config.LLM_MODEL == "claude-opus-5-5"
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 16000
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["fallbacks"] == "default"
    assert kwargs["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
    assert kwargs["system"] == [{"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]          # no assistant prefill
    assert not FORBIDDEN & set(kwargs)
    assert set(kwargs) == {"model", "max_tokens", "betas", "fallbacks", "output_config", "system", "messages"}


def test_text_call_request_shape_and_text_blocks():
    content = [SimpleNamespace(type="thinking", thinking=""),
               SimpleNamespace(type="fallback", from_=SimpleNamespace(model="claude-opus-5-5"),
                               to=SimpleNamespace(model="claude-opus-5")),
               SimpleNamespace(type="text", text="Answer "), SimpleNamespace(type="text", text="text.")]
    client = FakeClient(response(content=content))
    assert text_call("SYS", "Q?", effort="medium", client=client) == "Answer text."
    (kwargs,) = client.calls
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["fallbacks"] == "default" and not FORBIDDEN & set(kwargs)


def test_claude_extractor_request_uses_the_cached_semantic_model_prompt():
    client = FakeClient(response(hero_payload()))
    ClaudeExtractor(client=client).extract(hero_record())
    (kwargs,) = client.calls
    assert kwargs["output_config"]["effort"] == config.LLM_EXTRACTION_EFFORT
    assert kwargs["output_config"]["format"] == {"type": "json_schema", "schema": extraction_schema()}
    system = kwargs["system"][0]["text"]
    assert system == system_prompt() and kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    for fragment in ["CMP-NVDA | Company | Nvidia | NVIDIA; NVIDIA Corporation; NVDA",
                     "IC-2026-004 | Decision | Increase AI Infrastructure Fund allocation",
                     "decided 2026-02-12", "CON-GPU GPU Capacity: GPU capacity", "PER-001 | Person | Douglas Whitfield",
                     "- MENTIONS: Document -> Person | Company | Fund | Client | Theme | Concept",
                     "COM-IC | Committee | Investment Committee | IC", "NEW:<Name>", "MEETING", "DOCUMENT"]:
        assert fragment in system, fragment
    user = kwargs["messages"][0]["content"]
    assert "Document id: DOC-MN-03" in user and "Participants: Douglas Whitfield; Meredith Calloway" in user
    assert "<document_body>\nDiscussion:\nWe remain bullish on Nvidia" in user


def test_system_prompt_is_identical_for_every_document():
    first = system_prompt()
    other = user_message(hero_record(), [])
    assert system_prompt() == first and "DOC-MN-03" not in first and "DOC-MN-03" in other


def test_schema_is_strict_and_built_from_the_ontology():
    schema = extraction_schema()
    onto = load_ontology()
    assert anthropic.transform_schema(schema) == schema                 # already in the SDK's strict form

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from objects(value)

    for obj in objects(schema):
        assert obj["additionalProperties"] is False and obj["required"] == list(obj["properties"])
    labels = schema["properties"]["entities"]["items"]["properties"]["label"]["enum"]
    types = schema["properties"]["relationships"]["items"]["properties"]["type"]["enum"]
    assert labels == [l for l, e in onto.entities.items() if e.extractable]
    assert "Document" not in labels and "Advisor" not in labels
    assert types == [t for t, r in onto.relationships.items() if r.origin == "extracted"]
    assert "OWNS" not in types and "MENTIONS" in types


# ---------------------------------------------------------------------------- engine output
def test_canned_hero_output_matches_the_rules_engine():
    record = hero_record()
    claude = extract_record(record, engine="claude", client=FakeClient(response(hero_payload())))
    rules = extract_record(record, engine="rules")
    assert claude.engine == "claude:claude-opus-5-5" and claude.warnings == []
    assert _graph(claude) == _graph(rules)
    assert claude.meeting == rules.meeting and claude.document == rules.document
    assert {r.method for r in claude.relationships} == {"llm"}
    nvda = next(e for e in claude.entities if e.key == "Company:CMP-NVDA")
    assert nvda.origin == "text" and [record.text[s:t] for s, t in nvda.spans] == ["Nvidia"]
    john = next(e for e in claude.entities if e.key == "Person:PER-001")
    assert john.origin == "header"


def test_concept_only_output_gets_the_inferred_theme_like_the_rules_engine():
    text = HERO_TEXT.replace("We remain bullish on Nvidia and other AI infrastructure providers.",
                             "We remain bullish on Nvidia.")
    record = hero_record(text)
    payload = hero_payload()
    payload["entities"] = [e for e in payload["entities"] if e["ref"] != "THM-AI"]
    payload["relationships"] = [r for r in payload["relationships"] if r["target"] != "THM-AI"]
    claude = extract_record(record, engine="claude", client=FakeClient(response(payload)))
    assert _graph(claude) == _graph(extract_record(record, engine="rules"))
    inferred = next(r for r in claude.relationships if (r.source, r.type, r.target) == (HERO_DOC, "MENTIONS",
                                                                                        "Theme:THM-AI"))
    assert inferred.properties == {"inferred": True, "via": "GPU Capacity"}


def test_header_facts_are_added_when_claude_omits_them():
    payload = hero_payload()
    payload["entities"] = [e for e in payload["entities"] if e["label"] != "Person"]
    payload["relationships"] = [r for r in payload["relationships"] if r["type"] not in ("ATTENDED", "HELD_BY")]
    claude = extract_record(hero_record(), engine="claude", client=FakeClient(response(payload)))
    methods = {(r.source, r.type, r.target): r.method for r in claude.relationships}
    assert methods[("Person:PER-001", "ATTENDED", HERO_MEETING)] == "header"
    assert methods[("Person:PER-002", "ATTENDED", HERO_MEETING)] == "header"
    assert methods[(HERO_MEETING, "HELD_BY", "Committee:COM-IC")] == "header"
    assert _graph(claude) == _graph(extract_record(hero_record(), engine="rules"))


def test_new_entities_are_unresolved_candidates_and_the_catalog_wins():
    payload = hero_payload()
    payload["entities"] += [
        {"ref": "NEW:Jane Doe", "label": "Person", "name": "Jane Doe", "mentions": ["Jane Doe"]},
        {"ref": "NEW:Taiwan Semiconductor", "label": "Company", "name": "Taiwan Semiconductor", "mentions": []},
        {"ref": "NEW:Quantum Widgets", "label": "Theme", "name": "Quantum Widgets", "mentions": []},
        {"ref": "FND-AIX", "label": "Company", "name": "AI Infrastructure Fund", "mentions": []},
        {"ref": "CMP-MADEUP", "label": "Company", "name": "Madeup Corp", "mentions": []},
    ]
    payload["relationships"] += [
        {"source": "DOCUMENT", "type": "MENTIONS", "target": "new: Jane  Doe", "evidence": "Jane Doe joined."},
        {"source": "DOCUMENT", "type": "MENTIONS", "target": "NEW:Taiwan Semiconductor", "evidence": "TSMC"},
        {"source": "DOCUMENT", "type": "MENTIONS", "target": "NEW:Quantum Widgets", "evidence": "x"},
        {"source": "DOCUMENT", "type": "MENTIONS", "target": "CMP-MADEUP", "evidence": "x"},
        {"source": "DOCUMENT", "type": "MENTIONS", "target": "COM-IC", "evidence": "x"},
        {"source": "MEETING", "type": "DECIDED", "target": "IC-2026-004", "evidence": "x"},
    ]
    text = HERO_TEXT.replace("through 2027.\n", "through 2027.\nJane Doe joined.\n")
    claude = extract_record(hero_record(text), engine="claude", client=FakeClient(response(payload)))
    entities = {e.key: e for e in claude.entities}
    jane = entities["Person:NEW-PERSON-JANE-DOE"]
    assert jane.resolved is False and jane.name == "Jane Doe" and jane.spans
    assert (HERO_DOC, "MENTIONS", "Person:NEW-PERSON-JANE-DOE") in {(r.source, r.type, r.target)
                                                                    for r in claude.relationships}
    assert entities["Company:CMP-TSM"].resolved                     # NEW name resolved through the catalog
    assert entities["Fund:FND-AIX"].label == "Fund"                 # the catalog's label wins
    assert not any("QUANTUM" in k or "MADEUP" in k for k in entities)
    assert not any(r.type == "DECIDED" for r in claude.relationships)   # decided 2026-02-12, not 2026-01-15
    assert "Decision:IC-2026-004" not in entities                      # no dangling entity from the rejected fact
    joined = "\n".join(claude.warnings)
    for fragment in ["catalog entity Company:CMP-TSM", "the catalog says Fund", "cannot be added by extraction",
                     "'CMP-MADEUP'", "does not allow Document -MENTIONS-> Committee",
                     "decision log dates it 2026-02-12"]:
        assert fragment in joined, fragment


def test_meeting_comes_from_the_header_and_is_never_invented():
    payload = hero_payload(meeting={"records_meeting": True, "title": "IC meeting (January)", "date": "2026-01-16",
                                    "meeting_type": "Investment Committee"})
    claude = extract_record(hero_record(), engine="claude", client=FakeClient(response(payload)))
    assert [e.key for e in claude.entities if e.label == "Meeting"] == [HERO_MEETING]
    assert any("header used" in w for w in claude.warnings)

    rules_email = extract_record(_email_record(), engine="rules")
    payload = {"meeting": {"records_meeting": True, "title": "Call", "date": "2026-01-16", "meeting_type": ""},
               "entities": [], "relationships": [{"source": "DOCUMENT", "type": "RECORDS", "target": "MEETING",
                                                  "evidence": "x"}]}
    claude = extract_record(_email_record(), engine="claude", client=FakeClient(response(payload)))
    assert not [e for e in claude.entities if e.label == "Meeting"]
    assert {e.key for e in claude.entities} == {e.key for e in rules_email.entities} - {
        e.key for e in rules_email.entities if e.origin == "text"}
    assert any("only meeting notes record meetings" in w for w in claude.warnings)


def _email_record():
    from kgdemo.manifest import doc_specs
    from test_extraction import compose_record, placeholder_body
    spec = next(s for s in doc_specs() if s.doc_id == "DOC-EM-04")
    return compose_record(spec, placeholder_body(spec))


def test_cited_documents_are_offered_with_their_ids():
    from kgdemo.manifest import doc_specs
    from test_extraction import compose_record, placeholder_body
    specs = {s.doc_id: s for s in doc_specs()}
    memo = compose_record(specs["DOC-ICM-03"], placeholder_body(specs["DOC-ICM-03"]))
    index = {"gpu demand outlook 2026-2027: capacity remains tight": "DOC-RR-01"}
    payload = {"meeting": {"records_meeting": False, "title": "", "date": "", "meeting_type": ""},
               "entities": [], "relationships": [{"source": "DOCUMENT", "type": "CITES", "target": "DOC-RR-01",
                                                  "evidence": "GPU Demand Outlook 2026-2027: Capacity Remains Tight"}]}
    client = FakeClient(response(payload))
    ex = extract_record(memo, engine="claude", title_index=index, client=client)
    prompt = client.calls[0]["messages"][0]["content"]
    assert "GPU Demand Outlook 2026-2027: Capacity Remains Tight [DOC-RR-01]" in prompt
    cites = [r for r in ex.relationships if r.type == "CITES"]
    assert [(r.target, r.method) for r in cites] == [("Document:DOC-RR-01", "llm")]
    assert sum("unresolved citation" in w for w in ex.warnings) == 3


# ---------------------------------------------------------------------------- failures
def test_refusal_raises_llm_refusal_and_extraction_falls_back():
    refused = response(content=[], stop_reason="refusal",
                       stop_details=SimpleNamespace(category="cyber", explanation=None))
    with pytest.raises(LLMRefusal, match="category: cyber"):
        structured_call("S", "U", {"type": "object"}, effort="low", client=FakeClient(refused))
    ex = extract_record(hero_record(), engine="claude", client=FakeClient(refused))
    assert ex.engine == "rules"
    assert ex.warnings[0].startswith("claude extraction unavailable (Claude declined the request")


def test_truncated_or_invalid_output_is_an_llm_error():
    with pytest.raises(LLMError, match="max_tokens"):
        structured_call("S", "U", {}, effort="low", client=FakeClient(response({}, stop_reason="max_tokens")))
    with pytest.raises(LLMError, match="invalid JSON"):
        structured_call("S", "U", {}, effort="low", client=FakeClient(response("{not json")))
    with pytest.raises(LLMError, match="no text"):
        text_call("S", "U", effort="low", client=FakeClient(response(content=[SimpleNamespace(type="thinking")])))
    ex = extract_record(hero_record(), engine="claude", client=FakeClient(response({"entities": "nope"})))
    assert ex.engine == "rules" and "does not match the extraction schema" in ex.warnings[0]


def test_without_credentials_extraction_falls_back_to_rules(no_credentials):
    assert not config.llm_available()
    with pytest.raises(LLMUnavailable):
        llm.get_client()
    ex = extract_record(hero_record(), engine="claude")
    assert ex.engine == "rules"
    assert ex.warnings[0].startswith("claude extraction unavailable (")
    assert ex.warnings[0].endswith("); used rules engine")
    assert {(r.source, r.type, r.target) for r in ex.relationships} == {
        (r.source, r.type, r.target) for r in extract_record(hero_record()).relationships}


def test_extract_all_with_claude_falls_back_per_document(no_credentials, tmp_path):
    out = extract_all([_email_record(), hero_record()], engine="claude", out_dir=tmp_path, max_workers=2)
    assert [e.doc_id for e in out] == ["DOC-EM-04", "DOC-MN-03"] and [e.engine for e in out] == ["rules", "rules"]
    assert all("used rules engine" in e.warnings[0] for e in out)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["DOC-EM-04.json", "DOC-MN-03.json"]


def test_extract_all_with_claude_uses_one_client_across_threads(tmp_path):
    client = FakeClient(response(hero_payload()))
    out = extract_all([hero_record(), _email_record()], engine="claude", out_dir=tmp_path, max_workers=2,
                      client=client)
    assert len(client.calls) == 2 and {e.engine for e in out} == {"claude:claude-opus-5-5"}
    hero = next(e for e in out if e.doc_id == "DOC-MN-03")
    assert _graph(hero) == _graph(extract_record(hero_record(), engine="rules"))


@pytest.mark.parametrize("error, expected", [
    (anthropic.AuthenticationError("invalid x-api-key", response=_http_response(401), body=None), LLMUnavailable),
    (anthropic.PermissionDeniedError("forbidden", response=_http_response(403), body=None), LLMUnavailable),
    (anthropic.RateLimitError("slow down", response=_http_response(429), body=None), LLMError),
    (anthropic.InternalServerError("boom", response=_http_response(500), body=None), LLMError),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")), LLMError),
])
def test_sdk_errors_are_mapped(error, expected):
    with pytest.raises(expected) as info:
        structured_call("S", "U", {}, effort="low", client=FakeClient(error))
    assert type(info.value) is expected                     # most specific mapping, not just the base class
    assert info.value.__cause__ is error
    ex = extract_record(hero_record(), engine="claude", client=FakeClient(error))
    assert ex.engine == "rules" and ex.warnings[0].endswith("); used rules engine")


# ---------------------------------------------------------------------------- the real SDK, offline
def wire_client(status: int = 200, message: dict | None = None, captured: list | None = None) -> anthropic.Anthropic:
    """A real anthropic.Anthropic whose HTTP transport is a local mock: checks the SDK accepts and
    serializes our parameters, and that real response objects parse."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        if captured is not None:
            captured.append((request, json.loads(request.content)))
        if status != 200:
            return httpx2.Response(status, json={"type": "error", "error": {"type": "api_error", "message": "nope"}})
        return httpx2.Response(200, json={"id": "msg_test", "type": "message", "role": "assistant",
                                          "model": "claude-opus-5-5", "stop_sequence": None,
                                          "usage": {"input_tokens": 1, "output_tokens": 1}, **(message or {})})
    return anthropic.Anthropic(api_key="test-key", max_retries=0,
                               http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))


def _message(payload: dict, *, stop_reason: str = "end_turn", stop_details=None, fallback: bool = False) -> dict:
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    if fallback:
        content.append({"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-5"},
                        "trigger": {"type": "refusal", "category": "cyber"}})
    if payload is not None:
        content.append({"type": "text", "text": json.dumps(payload)})
    return {"content": content, "stop_reason": stop_reason, "stop_details": stop_details}


def test_wire_request_from_the_real_sdk():
    captured: list = []
    client = wire_client(message=_message(hero_payload(), fallback=True), captured=captured)
    claude = extract_record(hero_record(), engine="claude", client=client)
    assert _graph(claude) == _graph(extract_record(hero_record(), engine="rules"))
    ((request, body),) = captured
    assert request.url.path == "/v1/messages" and request.url.params.get("beta") == "true"
    assert request.headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert set(body) == {"model", "max_tokens", "messages", "fallbacks", "output_config", "system"}
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default" and body["max_tokens"] == 16000
    assert body["output_config"] == {"effort": config.LLM_EXTRACTION_EFFORT,
                                     "format": {"type": "json_schema", "schema": extraction_schema()}}
    assert body["system"] == [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    assert [m["role"] for m in body["messages"]] == ["user"]


@pytest.mark.parametrize("status, expected", [(401, LLMUnavailable), (403, LLMUnavailable), (429, LLMError),
                                              (500, LLMError), (400, LLMError)])
def test_wire_http_errors_are_mapped(status, expected):
    with pytest.raises(expected) as info:
        text_call("S", "U", effort="low", client=wire_client(status))
    assert type(info.value) is expected and f"HTTP {status}" in str(info.value)


def test_wire_refusal_and_truncation():
    refusal = _message(None, stop_reason="refusal",
                       stop_details={"type": "refusal", "category": "bio", "explanation": "declined"})
    with pytest.raises(LLMRefusal, match="category: bio"):
        structured_call("S", "U", {"type": "object"}, effort="low", client=wire_client(message=refusal))
    with pytest.raises(LLMError, match="max_tokens"):
        structured_call("S", "U", {"type": "object"}, effort="low",
                        client=wire_client(message=_message({"partial": 1}, stop_reason="max_tokens")))


def test_authentication_error_message_is_explicit():
    error = anthropic.AuthenticationError("invalid x-api-key", response=_http_response(401), body=None)
    with pytest.raises(LLMUnavailable, match="rejected the credentials \\(HTTP 401\\): invalid x-api-key"):
        text_call("S", "U", effort="low", client=FakeClient(error))
