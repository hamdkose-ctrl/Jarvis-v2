"""Turn verified research receipts into a direct user-facing answer without another model call.

Research already spent its model/tool budget obtaining verified literal evidence. Delivery
must not consume a second provider quota or steal planner responses; it promotes the
verified findings to the user-facing text while preserving the sealed receipt.
"""
from __future__ import annotations
import copy
import re

from modules import task_results


def synthesize(output,request):
    """Re-seal a news receipt with evidence-first chat text, preserving all proof fields."""
    task_results.verify(output)
    article=output.get('news_article')
    quotes=output.get('source_quotes')
    if not isinstance(article,dict) or not isinstance(quotes,list) or not quotes:
        return output
    findings=[]
    for quote in quotes:
        text=re.sub(r'\s+',' ',str(quote)).strip()
        if text and text not in findings:findings.append(text)
        if len(findings)>=3:break
    if not findings:return output
    answer=' '.join(findings)
    if len(answer)>1800:answer=answer[:1797].rstrip()+'...'
    refreshed=copy.deepcopy(output);refreshed.pop('verification',None)
    refreshed['text']=answer+'\nYayın tarihi: '+article['published']+'\nKaynak: '+article['url']
    return task_results.seal('research',refreshed)
