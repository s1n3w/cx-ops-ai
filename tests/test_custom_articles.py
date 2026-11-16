"""Your own articles: saved outside the repo, used by the app, never by the scored tests."""
import pytest

from cxops import data


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CUSTOM_FILE", tmp_path / "my-articles.json")
    monkeypatch.setattr(data, "use_custom", False)


def test_add_edit_delete():
    a = data.save_custom_article("Phone support hours", "Call us Monday to Friday, 8 a.m. to 6 p.m. Eastern.")
    assert a["id"] == "my01" and data.custom_articles()["my01"]["title"] == "Phone support hours"
    data.save_custom_article("Phone support hours", "Now 7 a.m. to 7 p.m.", "my01")
    assert "7 p.m." in data.custom_articles()["my01"]["body"]
    assert data.save_custom_article("Second", "Text")["id"] == "my02"
    data.delete_custom_article("my01")
    assert list(data.custom_articles()) == ["my02"]
    assert data.save_custom_article("Third", "Text")["id"] == "my01"   # ids are reused once free


def test_custom_articles_only_count_when_the_app_turns_them_on():
    data.save_custom_article("Phone support hours", "Call us weekdays.")
    assert "my01" not in data.articles()          # evals and the CLI tools: built-in set only
    data.use_custom = True
    assert "my01" in data.articles() and "kb01" in data.articles()


def test_validation():
    with pytest.raises(ValueError):
        data.save_custom_article("", "body")
    with pytest.raises(ValueError):
        data.save_custom_article("title", "   ")
    with pytest.raises(ValueError):
        data.save_custom_article("title", "body", "my99")
    long = data.save_custom_article("Long", "x" * 5000)
    assert len(long["body"]) == data.MAX_CUSTOM_BODY


def test_limit():
    for i in range(data.MAX_CUSTOM):
        data.save_custom_article(f"A{i}", "text")
    with pytest.raises(ValueError):
        data.save_custom_article("one too many", "text")
