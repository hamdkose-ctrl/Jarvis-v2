"""Model-free dated-news reading for durable research.

A verified single article is evidence on its own. This module extracts a few literal,
query-relevant sentences and seals them as a normal research receipt without consuming
an LLM/provider quota. It never invents claims or publication dates.
"""
from __future__ import annotations
import re

from modules import privacy, public_sources, research_delivery, research_evidence, requests_state, task_results

_STOP={
    'haber','haberler','haberleri','haberi','guncel','güncel','son','durum','nelerdir','nedir','neler','ne','var','bugun','bugün',
    'anlat','anlatir','anlatır','gelisme','gelişme','gelismeler','gelişmeler','hakkinda','hakkında','icin','için',
    'ara','arastir','araştır','bak','bakar','latest','news','recent','today','what','about','the','and','ile','bir',
}


def _fold(value):
    return str(value).casefold().replace('ı','i').replace('\u0307','')


def terms(value):
    """Return topical words only; generic news/request words do not create false relevance."""
    result=[]
    topical = re.sub(r'\bson\s+dakika\b', ' ', _fold(value))
    for word in re.findall(r'[\wçğıöşüâîû-]+',topical,re.UNICODE):
        word=word.strip('-_')
        if len(word)<3 or word in _STOP or word.isdigit():continue
        if word not in result:result.append(word)
        if len(result)>=16:break
    return result


def _ai_scope_ok(article, request):
    """If AI is an explicit requested subject, the article itself must contain AI evidence."""
    wanted=_fold(request)
    ai_requested=(re.search(r'\byapay\s+zek',wanted) is not None or
                  'artificial intelligence' in wanted or re.search(r'\bai\b',wanted) is not None)
    if not ai_requested:
        return True
    haystack=_fold((article.get('title') or '')+' '+(article.get('text') or ''))
    return bool(re.search(r'\byapay\s+zek',haystack) or 'artificial intelligence' in haystack or
                re.search(r'\bai\b',haystack))


def _turkiye_scope_ok(article, request):
    """If Türkiye is explicitly requested, the article itself must contain Türkiye evidence."""
    wanted=_fold(request)
    if not re.search(r'\b(?:türkiye|turkiye|turkey)\b', wanted):
        return True
    haystack=_fold((article.get('title') or '')+' '+(article.get('text') or ''))
    return bool(re.search(
        r'\b(?:türkiye|turkiye|turkey|türk|turk|turkish|istanbul|ankara|izmir)\b',
        haystack,
    ))


def _sentences(text):
    text=re.sub(r'\s+',' ',str(text)).strip()
    rows=[]
    for match in re.finditer(r'[^.!?]+(?:[.!?]+|$)',text):
        sentence=match.group(0).strip()
        if 25<=len(sentence)<=800:rows.append((match.start(),sentence))
    return rows


def quotes(article,request):
    """Pick 1-3 exact article sentences. If topical terms exist, require at least one match."""
    if not _turkiye_scope_ok(article,request):
        raise ValueError('Tekil haber istenen Türkiye kapsamını kanıtlamıyor.')
    if not _ai_scope_ok(article,request):
        raise ValueError('Tekil haber kullanıcının istediği yapay zekâ konusuyla eşleşmiyor; başka gerçek haber bağlantısı seç.')
    text=re.sub(r'\s+',' ',article['text']).strip()
    title=re.sub(r'\s+',' ',article['title']).strip()
    if text.startswith(title):text=text[len(title):].lstrip(' :-–—')
    rows=_sentences(text)
    if not rows:raise ValueError('Haber gövdesinde aktarılabilir tam cümle bulunamadı.')
    wanted=terms(request)
    folded_title=_fold(title)
    scored=[]
    for pos,sentence in rows:
        folded=_fold(sentence)
        score=sum(3 for term in wanted if term in folded)+sum(2 for term in wanted if term in folded_title)
        scored.append((score,pos,sentence))
    if wanted and max((row[0] for row in scored),default=0)<=0:
        raise ValueError('Tekil haber kullanıcının istediği konuyla eşleşmiyor; başka gerçek haber bağlantısı seç.')
    selected=sorted(scored,key=lambda row:(-row[0],row[1]))[:3]
    if not wanted:selected=scored[:3]
    selected=sorted(selected,key=lambda row:row[1])
    result=[]
    for _,_,sentence in selected:
        sentence=re.sub(r'\s+',' ',sentence).strip()
        if sentence not in result:result.append(sentence)
    if not result:raise ValueError('Haber gövdesinden doğrulanabilir alıntı seçilemedi.')
    return result


def run(owner,data,request,*,source_only=False):
    """Fetch, verify and render one dated article without any LLM call."""
    if blocked:=privacy.blocked('web'):raise PermissionError(blocked)
    requests_state.check()
    if not isinstance(data,dict) or not isinstance(data.get('url'),str):raise ValueError('Araştırma için haber adresi gerekli.')
    response=public_sources.fetch(data['url'])
    article=research_evidence.article(response)
    research_evidence.news_date(article['published'],request or data.get('question',''))
    evidence=quotes(article,(request+' '+data.get('question','')).strip())
    raw={'state':'done','text':' '.join(evidence),'source':article['url'],'source_chars':len(article['text']),
         'source_quotes':evidence,'source_only':bool(source_only),'news_article':article}
    sealed=task_results.seal('research',raw)
    return sealed if source_only else research_delivery.synthesize(sealed,request)
