"""Bounded Ollama embedding batches, with explicit legacy endpoint compatibility."""
import math
import requests
from modules import requests_state


def _vectors(value,count):
    if not isinstance(value,list) or len(value)!=count:
        raise ValueError('Yerel gömme yanıtında vektör sayısı uyuşmuyor.')
    if any(not isinstance(row,list) or not row or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in row) for row in value):
        raise ValueError('Yerel gömme yanıtı geçersiz.')
    return value


def run(texts,url,model):
    out=[]
    legacy=False
    for offset in range(0,len(texts),50):
        part=texts[offset:offset+50]
        requests_state.check()
        if not legacy:
            response=requests.post(url+'/api/embed',json={'model':model,'input':part,'truncate':False},timeout=60)
            # A model-not-found JSON 404 is a real model error, not an old API.
            legacy=response.status_code==405 or (response.status_code==404 and response.text.strip()=='404 page not found')
            if not legacy:
                response.raise_for_status()
                out.extend(_vectors(response.json().get('embeddings'),len(part)))
        if legacy:
            for text in part:
                requests_state.check()
                response=requests.post(url+'/api/embeddings',json={'model':model,'prompt':text},timeout=60)
                response.raise_for_status()
                out.extend(_vectors([response.json().get('embedding')],1))
        requests_state.check()
    if out and any(len(row)!=len(out[0]) for row in out):
        raise ValueError('Yerel gömme vektör boyutları uyuşmuyor.')
    return out
