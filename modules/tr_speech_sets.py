"""Motorun Türkçe söyleyiş kümeleri; eski içerikler değiştirilmeden taşındı."""

WEATHER_STOP = frozenset({
    "bugün", "yarın", "şimdi", "şuan", "bana", "bugünkü", "acaba", "dışarı", "dışarıda", "burada",
    "bu", "şu", "bir", "ve", "hava", "nasıl", "ne", "kaç",
})

NAME_SUFFIXES = frozenset({"im", "yim", "ye", "ya", "de", "da", "in", "nin", "dir", "ydi"})

JARVIS_MISHEAR = frozenset({
    "servis", "travis", "carvis", "cervis", "jervis", "çarviş", "harvis", "garvis", "darvis",
    "yarış", "yarvis", "jarviş", "jarvisi", "service", "jarves", "javis", "carviş",
})
