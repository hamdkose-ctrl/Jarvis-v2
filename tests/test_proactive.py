from modules.proactive import suggest

def test_proactive_suggestions_include_risk_and_are_disableable():
    result = suggest("iş planı", risks=["tek kişiye bağımlılık"], opportunities=["yedek plan oluştur"])
    assert result[0]["text"].startswith("Burada dikkat et")
    assert result[0]["kind"] == "risk"
    assert suggest("iş planı", risks=["risk"], enabled=False) == []

def test_proactive_suggestions_ignore_empty_context():
    assert suggest("konu") == []
