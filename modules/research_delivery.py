"""Turn verified research receipts into a direct user-facing answer.

The evidence receipt remains authoritative. Synthesis may explain and combine what the
verified article supports, but it cannot create new source evidence. If every model route
is unavailable, the already verified research output is returned unchanged.
"""
from __future__ import annotations
import copy

from modules import task_results
from modules.diagnostics import record_failure as _record_failure


def _valid(value):
    if not isinstance(value,str) or not value.strip():
        raise ValueError('Araştırma sentezi boş.')
    if len(value)>5000:raise ValueError('Araştırma sentezi gereksiz uzun.')
    return value.strip()


def synthesize(output,request):
    """Re-seal a news research output with an answer-first text, preserving receipts."""
    task_results.verify(output)
    article=output.get('news_article')
    if not isinstance(article,dict) or not output.get('source_quotes'):
        return output
    from modules import model_wait
    prompt=(
        'Kullanıcının sorusu/hedefi:\n'+str(request or '').strip()+'\n\n'
        'DOĞRULANMIŞ HABER:\nBaşlık: '+article['title']+'\nYayın tarihi: '+article['published']+
        '\nKaynak: '+article['url']+'\n\nHaber metni:\n'+article['text'][:16000]+
        '\n\nDaha önce doğrulanan birebir alıntılar:\n- '+'\n- '.join(output['source_quotes'])
    )
    system=(
        'Yalnız verilen doğrulanmış haber metnine dayanarak kullanıcıya doğrudan Türkçe cevap ver. '
        'Başlık veya bağlantıyı cevap yerine koyma. Önce ne olduğunu söyle; kaynak destekliyorsa kim/ne yaptı, '
        'etkilenen kapsam ve neden önemli olabileceğini açıkla. Kaynakta olmayan sebep, sonuç, sayı, yer veya önem '
        'uydurma; yorum gerekiyorsa bunu açıkça sınırlı çıkarım olarak belirt. 2-6 kısa cümle yeterli. '
        'Kaynak URL, Markdown kaynak listesi, dosya yolu veya meta açıklama ekleme; bunları uygulama ayrıca gösterir.'
    )
    try:
        answer=model_wait.ask(prompt,system,max_tokens=700,validator=_valid)
        answer=_valid(answer)
    except Exception:
        _record_failure('modules/research_delivery.py:synthesize')
        return output
    refreshed=copy.deepcopy(output);refreshed.pop('verification',None)
    refreshed['text']=(answer+'\nYayın tarihi: '+article['published']+'\nKaynak: '+article['url'])
    return task_results.seal('research',refreshed)
