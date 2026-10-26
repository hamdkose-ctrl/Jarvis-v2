import pytest
from modules.guidance import build

def test_guidance_is_stepwise_and_explains_choice_and_risks():
    result = build("düzenli spor", ["takvime koy", "küçük başla"], options=[{"name": "sabah", "why": "güne erken başlar"}], risks=["aşırı yüklenme"])
    assert result["goal"] == "düzenli spor"
    assert result["steps"][0]["order"] == 1
    assert result["selected_option"]["name"] == "sabah"
    assert result["selected_option"]["why"] == "güne erken başlar"
    assert result["risks"][0]["mitigation"]

def test_guidance_requires_steps():
    with pytest.raises(ValueError):
        build("hedef", [])
