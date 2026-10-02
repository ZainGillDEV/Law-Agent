import sys
import types

import article_matcher
from article_matcher import _parse_llm, _validate, keyword_search, suggest_articles


def _fake_llm(reply=None, error=False):
    """Put a fake llm_client module in place, so no API key or network is needed."""
    mod = types.ModuleType("llm_client")

    def chat(system, user, **kwargs):
        if error:
            raise RuntimeError("LLM down")
        return reply

    mod.chat = chat
    sys.modules["llm_client"] = mod


def test_parse_llm_json():
    assert _parse_llm('{"articles": ["152", "156"]}') == ["152", "156"]
    assert _parse_llm('Sure! {"articles": ["57"]} hope this helps') == ["57"]
    assert _parse_llm("no json here") == []
    assert _parse_llm('{"articles": "152"}') == []


def test_validate_drops_unknown_and_duplicates():
    arts = _validate(["999", "152", "152", "156", "4"], limit=3)
    assert [a.article for a in arts] == ["152", "156"]


def test_validate_respects_limit():
    assert len(_validate(["152", "156", "57", "142"], limit=3)) == 3


def test_suggest_uses_llm_result():
    _fake_llm('{"articles": ["152"]}')
    assert [a.article for a in suggest_articles("appeal against civil judge decree")] == ["152"]


def test_suggest_ignores_invented_articles():
    _fake_llm('{"articles": ["999", "152"]}')
    assert [a.article for a in suggest_articles("appeal")] == ["152"]


def test_suggest_falls_back_when_llm_fails():
    _fake_llm(error=True)
    result = suggest_articles("suit for arrears of rent")
    assert result and result[0].article == "110"


def test_keyword_search_dower():
    assert "104" in [a.article for a in keyword_search("deferred dower after divorce")]


def test_keyword_search_empty():
    assert keyword_search("ka ki ke") == []
