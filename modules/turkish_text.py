"""Locale-independent Turkish casing for user text comparisons."""
import unicodedata

_ASCII = str.maketrans('çğıöşü', 'cgiosu')


def lower(text):
    text = unicodedata.normalize('NFC', str(text or ''))
    return text.replace('İ', 'i').replace('I', 'ı').lower()


def fold(text):
    return lower(text).translate(_ASCII)
