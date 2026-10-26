import pytest
from modules.honest_critic import critique

def test_critique_is_direct_respectful_and_structured():
    result = critique("iş planı", ["hedef ölçülebilir değil"], strengths=["motivasyon var"])
    assert result["topic"] == "iş planı"
    assert result["points"][0]["text"].startswith("Buradaki zayıf nokta şu çünkü")
    assert result["tone"] == "dürüst ve saygılı"

def test_critique_requires_weaknesses():
    with pytest.raises(ValueError):
        critique("konu", [])
