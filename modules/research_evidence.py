"""A research answer needs an explicit result and literal evidence from the fetched page."""
import json
import re


def parse(answer,source,*,allow_unsupported=False):
    try:
        data=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',str(answer).strip()))
    except (ValueError,TypeError):
        raise ValueError('Araştırma yanıtında kaynak alıntısı yok; başarı sayılmadı.') from None
    if allow_unsupported and isinstance(data,dict) and set(data)=={'supported','answer','quotes'} and data['supported'] is False and data['answer']=='' and data['quotes']==[]:return data
    if not isinstance(data,dict) or set(data)!={'supported','answer','quotes'} or data['supported'] is not True:
        raise ValueError('Kaynak soruyu yanıtlamıyor; başarı sayılmadı. Başka ilgili kaynak gerekli.')
    if not isinstance(data['answer'],str) or not data['answer'].strip():raise ValueError('Araştırma yanıtı boş; başarı sayılmadı.')
    quotes=data['quotes']
    if not isinstance(quotes,list) or not 1<=len(quotes)<=5:raise ValueError('1–5 gerçek kaynak alıntısı gerekli; başarı sayılmadı.')
    normalized=lambda value:re.sub(r'\s+',' ',value).strip()
    text=normalized(source)
    if any(not isinstance(q,str) or not 20<=len(q)<=800 or normalized(q) not in text for q in quotes):
        raise ValueError('Araştırma alıntısı okunan sayfada yok; başarı sayılmadı.')
    return data
