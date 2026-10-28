"""Owner-run acceptance checks. Live accounts/desktop require explicit flags."""
import argparse
import json
from pathlib import Path
import platform
import re
import tempfile
from datetime import datetime,timezone
from modules.diagnostics import record_failure as _record_failure


def _gmail_attachment(owner):
    from modules import account_tools,task_results
    result=account_tools.run(owner,{'service':'gmail','operation':'list_unread','limit':10})
    if result['state']!='done':return 'pending','Gmail okuma kullanılamıyor; bağlantı/izin kontrolü gerekli.'
    items=result['snapshot']['items'][:10]
    if not items:return 'pending','Ek kabulü için okunmamış mail bulunamadı.'
    for count,item in enumerate(items,1):
        message_id=item['id']
        listed=account_tools.run(owner,{'service':'gmail','operation':'list_attachments','message_id':message_id})
        if listed['state']!='done':return 'pending',f'{count}. mailin ek listesi alınamadı; kontrol tamamlanmadı.'
        supported=[row for row in listed['snapshot']['items'] if row['supported']]
        if not supported:continue
        result=account_tools.run(owner,{'service':'gmail','operation':'read_attachment','message_id':message_id,
                                       'attachment_index':supported[0]['index']})
        if result.get('state')!='done':raise ValueError('Seçilen ek okunamadı; ek kabulü başarılı sayılmadı.')
        snapshot=result.get('snapshot',{})
        if snapshot.get('operation')=='list_attachments':
            return 'pending','Seçilen mailin eki listeleme sonrası değişti veya artık yok; ek okuması doğrulanmadı.'
        attachment=snapshot.get('attachment',{})
        if (snapshot.get('operation')!='read_attachment' or snapshot.get('service')!='gmail' or
                snapshot.get('owner')!=owner or snapshot.get('message_id')!=message_id or
                attachment.get('index')!=supported[0]['index'] or
                not isinstance(attachment.get('body'),str) or not attachment['body'].strip()):
            raise ValueError('Ek okuma makbuzu seçilen kullanıcı/mail/ek veya okunabilir metinle eşleşmiyor.')
        # Do not skip an unreadable supported attachment to manufacture a successful result.
        sealed=task_results.seal('account',result);task_results.verify(sealed,owner=owner)
        return 'passed',f'Ek okundu ve doğrulandı; incelenen mail sayısı: {count}. Mail/ek içeriği rapora yazılmadı.'
    return 'pending',f'İlk {len(items)} okunmamış mailde desteklenen ek bulunamadı; yalnız bu sınırlı liste kontrol edildi.'


def _goal_signature(job):
    """Stable semantic snapshot; volatile timestamps are intentionally excluded."""
    keys=('id','owner','request','state','goals','steps','outputs','blocker','feedback')
    return json.dumps({key:job.get(key) for key in keys},ensure_ascii=False,sort_keys=True,default=str)


def _news_job_facts(job):
    """Validate every dated article receipt and count distinct publishers."""
    from modules import publisher_news,research_evidence
    articles=0;publishers=set();request=job.get('request','')
    outputs=job.get('outputs') if isinstance(job.get('outputs'),dict) else {}
    for output in outputs.values():
        if not isinstance(output,dict) or output.get('state')!='done' or not output.get('news_article'):continue
        source=research_evidence.news_receipt(output)
        research_evidence.news_date(source['published'],request)
        publisher=publisher_news.publisher_key(source['url'])
        if publisher:publishers.add(publisher)
        articles+=1
    return articles,publishers


def _news_failure_detail(job):
    """Only bounded redacted decision summaries leave the isolated goal store."""
    from modules import privacy
    detail=f"Haber hedefi tamamlanmadı: {job.get('state','unknown')}"
    states=[goal.get('state') for goal in job.get('goals',[]) if goal.get('state') in {'done','pending'}]
    recovery={}
    for step in job.get('steps',[]):
        tool=step.get('tool');state=step.get('state')
        if step.get('recovery') and tool in {'data','research','writer','verify'} and state in {'done','failed','blocked','approval','queued','running'}:
            key=tool+'.'+state;recovery[key]=recovery.get(key,0)+1
    detail+='; hedefler='+','.join(states[:8])
    try:
        articles,publishers=_news_job_facts(job)
        detail+=f'; makale={articles}; yayıncı={len(publishers)}'
    except (ValueError,PermissionError,OSError):
        _record_failure('modules/acceptance_checks.py:news_failure_receipts')
        detail+='; makale=geçersiz'
    detail+='; kurtarma='+(','.join(key+':'+str(value) for key,value in sorted(recovery.items())) or 'yok')
    pipeline=job.get('news_pipeline') if isinstance(job.get('news_pipeline'),dict) else {}
    health=pipeline.get('source_health') if isinstance(pipeline.get('source_health'),list) else []
    if health:
        summary=[]
        for row in health[:20]:
            if not isinstance(row,dict):continue
            label=privacy.redact(str(row.get('source') or row.get('url') or 'kaynak'),force=True)[:60]
            state=str(row.get('status') or 'unknown')
            summary.append(label+':'+state)
        detail+='; kaynak_sağlığı='+(','.join(summary) or 'yok')
    blocker=privacy.redact(str(job.get('blocker') or ''),force=True)[:240]
    if blocker:detail+='; '+blocker
    trace=job.get('decision_diagnostics',[])[-3:]
    if trace:
        detail+='; decision_diagnostics='+privacy.redact(json.dumps(trace,ensure_ascii=False),force=True)
    return detail


def _news_chat_resume(owner):
    """Run the real fileless-news turn in an isolated goal store, then verify closed-goal resume."""
    from modules import engine_runtime,goal_executor
    previous_store=goal_executor.STORE
    runtime=None
    with tempfile.TemporaryDirectory(prefix='jarvis-news-acceptance-') as temp_dir:
        goal_executor.STORE=Path(temp_dir)/'goals'
        try:
            runtime=engine_runtime.EngineContext()
            runtime.handle('hedef son dakika haberleri')
            job=goal_executor.latest(owner)
            if not job:return 'failed','Haber hedefi oluşturulmadı.'
            if job.get('state')!='done':
                return 'failed',_news_failure_detail(job)
            if any(isinstance(step,dict) and step.get('tool')=='writer' and step.get('started') is True
                   for step in job.get('steps') or []):
                return 'failed','Dosya istenmeyen haber hedefinde writer çalıştı.'
            articles,publishers=_news_job_facts(job)
            if articles<2 or len(publishers)<2:
                return 'failed',f'Haber kanıtı yetersiz: {articles} tarihli makale, {len(publishers)} yayıncı.'
            before=_goal_signature(job);job_id=job.get('id')
            reply=runtime.handle('devam')
            after=goal_executor.latest(owner)
            if not after or after.get('id')!=job_id or after.get('state')!='done':
                return 'failed','devam tamamlanmış haber hedefini değiştirdi veya yeniden açtı.'
            if _goal_signature(after)!=before:
                return 'failed','devam tamamlanmış haber hedefinin kalıcı kaydını değiştirdi.'
            answer=str(reply or '').casefold()
            if 'açık hedef yok' not in answer or 'tamamlandı' not in answer:
                return 'failed','devam tamamlanmış hedef için kapalı-hedef yanıtını vermedi.'
            return 'passed',f'{articles} tarihli makale / {len(publishers)} yayıncı doğrulandı; devam hedefi değiştirmedi.'
        finally:
            if runtime is not None:
                pool=getattr(runtime,'_prefetch_pool',None)
                if pool is not None:
                    try:pool.shutdown(wait=False,cancel_futures=True)
                    except Exception:
                        _record_failure('modules/acceptance_checks.py:news_prefetch_shutdown')
            goal_executor.STORE=previous_store


def run(*,suite=True,gmail=False,desktop=False,narration=False,public_data=False,video=False,news=False,
        manual_confirm=(),manual_reset=()):
    from modules import llm,personalization,service_health,validation
    owner=personalization.slugify(personalization.get_active())
    token=llm._key_context.set(owner)
    report={'version':1,'checked_at':datetime.now(timezone.utc).isoformat(),'checks':[]}
    def check(name,fn):
        try:state,detail=fn()
        except Exception as exc:
            _record_failure('modules/acceptance_checks.py:check')
            state,detail='failed',type(exc).__name__
        report['checks'].append({'check':name,'state':state,'detail':detail})
    try:
        from modules import manual_acceptance
        manual=manual_acceptance.update(owner,confirm=manual_confirm,reset=manual_reset)
        def source():
            import updater
            status=updater.verify_sync();state=status.get('sync_state','unknown')
            files=[f"{d['path']} ({d['kind']})" for d in status.get('local_change_details') or []]
            return ('passed' if state=='synced' else 'pending',state+(': '+', '.join(files) if files else ''))
        check('github_source',source)
        if suite:
            def regression():
                ok,log=validation.run_checks()
                match=re.search(r'Ran (\d+) tests',log)
                return ('passed' if ok else 'failed',('Python tests: '+match[1]) if match else 'release suite result')
            check('release_suite',regression)
        check('local_configuration',lambda:('informational',service_health.report(owner)))
        if video:
            def movie():
                from modules import media_setup
                result=media_setup.check()
                return ('passed' if result.get('ok') is True else 'failed',result['text'])
            check('video_runtime',movie)
        else:report['checks'].append({'check':'video_runtime','state':'pending','detail':'Run with --video for real local H.264/FFprobe check'})
        if public_data:
            from modules import public_data_acceptance
            report['checks'].extend(public_data_acceptance.run(owner))
        if gmail:
            check('gmail_attachment',lambda:_gmail_attachment(owner))
        else:report['checks'].append({'check':'gmail_attachment','state':'pending','detail':'Run with --gmail after connecting the account'})
        if desktop:
            def calc():
                if platform.system()!='Windows':return 'pending','Requires real Windows desktop'
                from modules import desktop_agent,system_control
                if desktop_agent._BUSY.locked():return 'pending','Another desktop task is running'
                previous=desktop_agent._load(owner)
                previous_id=previous.get('id') if previous else None
                opened=system_control.open_application('hesap makinesi')
                if getattr(opened,'ok',False) is not True:return 'failed','Calculator window not verified'
                desktop_agent.handle(owner,'PC görevi: Hesap Makinesi | 12 ile 7 topla',current=lambda:owner)
                job=desktop_agent._load(owner)
                if not job or job.get('id')==previous_id:return 'pending','No new Calculator task was accepted'
                return ('passed' if job and job['status']=='done' else 'pending','Check Calculator 19 and desktop task status')
            check('calculator',calc)
        else:report['checks'].append({'check':'calculator','state':'pending','detail':'Run with --desktop on Windows'})
        if news:check('news_chat_resume',lambda:_news_chat_resume(owner))
        else:report['checks'].append({'check':'news_chat_resume','state':'pending','detail':'Run with --news for live fileless news + completed-goal resume acceptance'})
        if narration:
            def voice():
                from modules import local_narration
                result=local_narration.check(owner)
                return ('passed' if result.get('ok') is True else 'pending','Local WAV generation; listening quality requires manual acceptance')
            check('local_narration',voice)
        for name in manual_acceptance.CHECKS:
            recorded=manual.get(name)
            report['checks'].append({'check':name,'state':'reported_passed' if recorded else 'pending',
                'detail':('User-reported on this computer at '+recorded+'; not an automated test; repeat after relevant changes') if recorded
                else 'Manual acceptance required; not claimed by regression tests'})
    finally:llm._key_context.reset(token)
    return report


def main():
    parser=argparse.ArgumentParser(description='Jarvis V2 acceptance checks; no external sends or automatic source update')
    parser.add_argument('--gmail',action='store_true');parser.add_argument('--desktop',action='store_true')
    parser.add_argument('--narration',action='store_true');parser.add_argument('--skip-suite',action='store_true')
    parser.add_argument('--public-data',action='store_true',help='Live keyless data reads and partial report verification; no models/accounts')
    parser.add_argument('--video',action='store_true',help='Generate and probe a short temporary local H.264 video')
    parser.add_argument('--news',action='store_true',help='Run live fileless news and completed-goal resume acceptance')
    from modules.manual_acceptance import CHECKS
    parser.add_argument('--confirm-manual',nargs='+',choices=CHECKS,default=[],help='Record only checks you personally completed on this PC')
    parser.add_argument('--reset-manual',nargs='+',choices=CHECKS,default=[],help='Forget previous manual declarations on this PC')
    parser.add_argument('--output',default='v2_kabul_sonucu.json')
    args=parser.parse_args();report=run(suite=not args.skip_suite,gmail=args.gmail,desktop=args.desktop,narration=args.narration,
        public_data=args.public_data,video=args.video,news=args.news,manual_confirm=args.confirm_manual,manual_reset=args.reset_manual)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in report['checks']:print(row['check']+': '+row['state'])
    return 1 if any(r['state']=='failed' for r in report['checks']) else 0

if __name__=='__main__':raise SystemExit(main())
