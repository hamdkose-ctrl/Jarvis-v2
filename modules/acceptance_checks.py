"""Owner-run acceptance checks. Live accounts/desktop require explicit flags."""
from modules import core_brain_adapter
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
        research_evidence.news_date(source,request)
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
    detail+=f"; aday={pipeline.get('articles_discovered',0)}; okunan={pipeline.get('articles_read',0)}"
    detail+=f"; pencere_dışı={pipeline.get('outside_window',0)}"
    reasons=pipeline.get('rejection_reasons')
    if isinstance(reasons,list):
        summaries=[]
        for row in reasons[:3]:
            if not isinstance(row,dict):continue
            reason=privacy.redact(' '.join(str(row.get('reason') or '').split()),force=True)[:160]
            if reason:summaries.append(str(row.get('count',0))+'x '+reason)
        if summaries:detail+='; makale_retleri='+' / '.join(summaries)
    health=pipeline.get('source_health') if isinstance(pipeline.get('source_health'),list) else []
    failed=[row for row in health if isinstance(row,dict) and row.get('status')=='failed' and row.get('reason')]
    if failed:
        detail+='; kaynak_hataları='+' / '.join(
            privacy.redact(' '.join(str(row['reason']).split()),force=True)[:120] for row in failed[:2])
    search=pipeline.get('public_discovery')
    if isinstance(search,dict):
        detail+='; web_keşfi='+str(search.get('state','unknown'))+'; web_aday='+str(search.get('candidates',0))
        if search.get('reason'):detail+='; web_hatası='+privacy.redact(str(search['reason']),force=True)[:200]
    samples=pipeline.get('rejected_candidates')
    if isinstance(samples,list):
        detail+='; reddedilen_adresler='+' / '.join(
            privacy.redact(str(row.get('url','')),force=True)[:240]+' => '+
            privacy.redact(str(row.get('reason','')),force=True)[:140]
            for row in samples[:12] if isinstance(row,dict))
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


def _news_turn(runtime, text, *, router_store, create_goal=False):
    """Canonical Core ingress with ONE declared semantic fixture, not live Brain acceptance.

    Only this fixture's candidate plan and adapter response are synthetic. The
    typed Router, envelope validator, Brain handoff and Core gates stay real.
    Restore the adapter BEFORE execution; downstream model calls remain blocked.
    The acceptance source uses the existing synchronous admission path, without
    claiming the running engine's background Scheduler has been exercised.
    """
    from unittest.mock import patch
    from uuid import uuid4
    from modules import brain_entry, brain_model_understanding, llm, requests_state, smart_router
    owner = runtime.profile.slug
    rid = 'news-acceptance-' + uuid4().hex
    spec = smart_router.ModelSpec('groq', 'acceptance-semantic-fixture')
    raw = json.dumps({
        'schema_version': brain_model_understanding.SCHEMA_VERSION,
        'operation': 'create_goal', 'conversation_relation': 'NEW_REQUEST',
        'temporal_need': 'RECENT', 'target_goal_ids': [],
        'goal': {'kind': 'goal', 'title': text[:brain_model_understanding.GOAL_CARD_TITLE_MAX]},
        'actions': [], 'confidence': 'HIGH',
        'clarification': {'required': False, 'question': None, 'reason_code': None},
    }, ensure_ascii=False)

    def fixture_plan(request):
        if not create_goal or (request.owner, request.request_id, request.profile) != (owner, rid, 'brain_understanding'):
            raise ValueError('Haber kabul fixture kapsamı dışında model isteği.')
        return smart_router.RoutePlan((spec,), (), 1)

    def fixture_response(request, candidate, prompt, system, **kwargs):
        fixture_plan(request)
        if candidate != spec or json.loads(prompt)['utterance'] != text:
            raise ValueError('Haber kabul fixture isteği eşleşmiyor.')
        return raw

    if not requests_state.register(owner, rid, seconds=180):
        raise ValueError('Haber kabul istek kimliği kaydedilemedi.')
    with requests_state.activate(owner, rid), llm.owner_context(owner):
        with patch.object(smart_router, '_STORE', router_store), patch.object(smart_router, '_HEALTH', {}), \
                patch.object(smart_router, 'plan', side_effect=fixture_plan), \
                patch.object(llm, 'dispatch', side_effect=fixture_response) as adapter:
            entry = brain_entry.prepare(runtime, owner=owner, request_id=rid, text=text,
                                        source='acceptance', model_understanding=True)
            if adapter.call_count != int(create_goal):
                raise ValueError('Haber kabulünde beklenmeyen anlamlandırma çağrı sayısı.')
        reply, _feedback, _job_id = core_brain_adapter.handoff(runtime, entry, runtime.handle, text)
        return reply


def _news_scenario(owner,request='son dakika haberleri',*,file_report=False):
    """Live news/Core workflow; semantic admission is a fixture, not a live model test."""
    from modules import engine_runtime,goal_executor,nxapi,llm,task_results,model_free_news
    from modules import personalization,task_agents,desktop_agent,history,filesend,requests_state
    from unittest.mock import patch
    from contextlib import ExitStack
    previous_store=goal_executor.STORE
    runtime=None
    with tempfile.TemporaryDirectory(prefix='jarvis-news-acceptance-') as temp_dir, ExitStack() as guards:
        files=Path(temp_dir)/'files'
        # News acceptance owns a fresh scenario, not the user's pending lesson,
        # learning consent, task job or desktop question. Keep the actual owner
        # and real privacy policy; isolate their MUTABLE scenario stores.
        profiles=Path(temp_dir)/'profiles'
        profiles.mkdir()
        with patch.object(personalization,'USERS_DIR',profiles):
            profile=personalization.Profile(personalization.get_active())
        if profile.slug != owner:
            raise PermissionError('Haber kabul kullanıcısı aktif profille eşleşmiyor.')

        def scenario_profile(name=None):
            if personalization.slugify(name or personalization.get_active()) != owner:
                raise PermissionError('Haber kabul profili başka kullanıcıya ait.')
            return profile

        guards.enter_context(patch.object(engine_runtime,'Profile',side_effect=scenario_profile))
        guards.enter_context(patch.object(engine_runtime,'migrate_legacy'))
        for module,attr,value in (
            (task_agents,'STORE',Path(temp_dir)/'tasks'),
            (desktop_agent,'STORE',Path(temp_dir)/'desktop'),
            (history,'DIR',Path(temp_dir)/'history'),
            (filesend,'_pending_by_owner',{}),
            (requests_state,'_journal',Path(temp_dir)/'requests.json'),
            (requests_state,'_records',{}),
        ):
            guards.enter_context(patch.object(module,attr,value))
        guards.enter_context(patch.object(nxapi,'FILES_DIR',files))
        model=guards.enter_context(patch.object(llm,'ask',side_effect=RuntimeError('Kabul sırasında model çağrısı kapalı.')))
        transport=guards.enter_context(patch.object(llm,'dispatch',side_effect=RuntimeError('Kabul sırasında canlı model taşıyıcısı kapalı.')))
        guards.enter_context(patch.object(goal_executor,'_quota_wait',return_value=60))
        goal_executor.STORE=Path(temp_dir)/'goals'
        try:
            runtime=engine_runtime.EngineContext()
            if runtime.profile.slug != owner:
                raise PermissionError('Haber kabul kullanıcısı aktif profille eşleşmiyor.')
            router_store=Path(temp_dir)/'router-fixture'
            _news_turn(runtime,request,router_store=router_store,create_goal=True)
            job=goal_executor.latest(owner)
            if not job:return 'failed','Haber hedefi oluşturulmadı.'
            if job.get('state')!='done':
                return 'failed',_news_failure_detail(job)
            if not file_report and any(isinstance(step,dict) and step.get('tool')=='writer' and step.get('started') is True
                   for step in job.get('steps') or []):
                return 'failed','Dosya istenmeyen haber hedefinde writer çalıştı.'
            articles,publishers=_news_job_facts(job)
            if articles<2 or len(publishers)<2:
                return 'failed',f'Haber kanıtı yetersiz: {articles} tarihli makale, {len(publishers)} yayıncı.'
            for output in job.get('outputs',{}).values():
                if isinstance(output,dict) and output.get('state')=='done' and output.get('news_article'):
                    model_free_news.quotes(output['news_article'],request)
            if file_report:
                reports=[(ident,output) for ident,output in job.get('outputs',{}).items()
                         if isinstance(output,dict) and output.get('state')=='done' and output.get('news_report_evidence')]
                if len(reports)!=1:return 'failed','Tek doğrulanmış haber raporu bulunamadı.'
                report_id,report=reports[0]
                task_results.verify(report,owner=owner)
                path=Path(report['file']).resolve()
                if not path.is_relative_to(files.resolve()):return 'failed','Rapor yalıtılmış dosya alanında değil.'
                count,hosts=_news_job_facts({'request':request,'outputs':report['news_report_evidence'].get('sources',{})})
                if count<2 or len(hosts)<2:return 'failed','Dosyanın kendi kanıtında iki yayıncı yok.'
                if not any(step.get('tool')=='verify' and step.get('state')=='done' and
                           report_id in step.get('depends',[]) for step in job.get('steps',[])):
                    return 'failed','Raporun verify adımı tamamlanmadı.'
                original_bytes=path.read_bytes()
            before=_goal_signature(job);job_id=job.get('id')
            reply=_news_turn(runtime,'devam',router_store=router_store)
            after=goal_executor.latest(owner)
            if not after or after.get('id')!=job_id or after.get('state')!='done':
                return 'failed','devam tamamlanmış haber hedefini değiştirdi veya yeniden açtı.'
            if _goal_signature(after)!=before:
                return 'failed','devam tamamlanmış haber hedefinin kalıcı kaydını değiştirdi.'
            answer=str(reply or '').casefold()
            if 'açık hedef yok' not in answer or 'tamamlandı' not in answer:
                return 'failed','devam tamamlanmış hedef için kapalı-hedef yanıtını vermedi.'
            if model.call_count or transport.call_count:return 'failed','Haber kabulünde canlı model çağrısı denendi.'
            if file_report and path.read_bytes()!=original_bytes:return 'failed','Devam rapor dosyasını değiştirdi.'
            return 'passed',f'{articles} tarihli makale / {len(publishers)} yayıncı doğrulandı; devam hedefi değiştirmedi. Anlamlandırma sabit fixture; canlı Brain/Scheduler kabulü değildir.'
        finally:
            if runtime is not None:
                pool=getattr(runtime,'_prefetch_pool',None)
                if pool is not None:
                    try:pool.shutdown(wait=False,cancel_futures=True)
                    except Exception:
                        _record_failure('modules/acceptance_checks.py:news_prefetch_shutdown')
            goal_executor.STORE=previous_store


def _news_external_discovery(owner):
    """Opt-in live probe: force an empty catalogue, keep real search and article reads."""
    from modules import news_pipeline,research_providers,publisher_news
    from urllib.parse import urlsplit
    request='Son 7 gün güncel haberleri araştır'
    catalog_keys={publisher_news.publisher_key(row['url']) for row in publisher_news.GENERAL_SOURCES}
    def external_search(query):
        return [row for row in research_providers.search_news_public(query)
                if publisher_news.publisher_key(row['url']) not in catalog_keys]
    result=news_pipeline.run(request,owner=owner,max_sources=0,searcher=external_search)
    discovery=result.get('public_discovery',{})
    from modules import privacy
    hosts={publisher_news.publisher_key(row['url']) for row in publisher_news.GENERAL_SOURCES}
    external=[row for row in result.get('candidates',[]) if row.get('verification')=='verified'
              and publisher_news.publisher_key(row['url']) not in hosts]
    detail=('Katalog boşluğu zorlandı; gerçek anahtarsız arama ve makale okuyucu; '
            f"keşif={discovery.get('state')}; aday={discovery.get('candidates',0)}; "
            f"okunan={result.get('articles_read',0)}; katalog_dışı_doğrulanan={len(external)}; "
            f"neden={discovery.get('reason') or 'yok'}; sağlayıcı={discovery.get('providers',[])}")
    rows=[]
    for row in result.get('candidates',[])[:8]:
        url=str(row.get('url',''))
        catalog=publisher_news.publisher_key(url) in hosts
        rows.append(privacy.redact(url)[:500]+' | katalog='+('içi' if catalog else 'dışı')+
                    ' | doğrulama='+str(row.get('verification','unknown'))+
                    ' | ret='+privacy.redact(str(row.get('reason') or 'yok'))[:300])
    if rows:detail+=' | aday_sonuçları: '+' || '.join(rows)
    return ('passed' if external else 'failed'),detail


def _news_chat_resume(owner):
    """All cases are required; a generic PASS cannot hide a topic or file failure."""
    cases=[('genel sohbet','Son 7 gün güncel haberleri araştır',False),
           ('Türkiye AI sohbet','Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır',False),
           ('Türkiye AI dosya','Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır ve raporu dosyaya kaydet',True)]
    summaries=[];failed=False
    for label,request,file_report in cases:
        try:
            state,detail=_news_scenario(owner,request,file_report=file_report)
        except Exception as exc:
            _record_failure('modules/acceptance_checks.py:news_scenario')
            state,detail='failed',type(exc).__name__
        failed=failed or state!='passed'
        summaries.append(label+': '+state+'; '+detail)
    return ('failed' if failed else 'passed'),('Core/haber iş akışı; sabit anlam fixture, canlı Brain/Scheduler kabulü değil. | '+' | '.join(summaries))


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
        if news:
            check('news_chat_resume',lambda:_news_chat_resume(owner))
            check('news_external_discovery',lambda:_news_external_discovery(owner))
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


def archive_news_result(report):
    """Persist bounded news diagnostics even when an older watcher removes its worktree."""
    import os
    import hashlib
    from uuid import uuid4
    from modules import privacy
    root=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local'/'share')/'Jarvis'/'pc-acceptance'/'news-reports'
    root.mkdir(parents=True,exist_ok=True)
    checks=[]
    for row in report.get('checks',[]):
        if isinstance(row,dict) and str(row.get('check','')).startswith('news'):
            checks.append({'check':str(row['check'])[:100],'state':str(row.get('state','unknown'))[:30],
                           'detail':privacy.redact(str(row.get('detail','')),force=True)[:16000]})
    digest=hashlib.sha256()
    for name in ('acceptance_checks.py','news_pipeline.py','research_evidence.py','publisher_news.py','research_providers.py'):
        digest.update(name.encode());digest.update(Path(__file__).with_name(name).read_bytes())
    stamp=datetime.now(timezone.utc)
    payload={'created_at':stamp.isoformat(),'code_fingerprint':digest.hexdigest(),'checks':checks}
    encoded=json.dumps(payload,ensure_ascii=False,indent=2)
    path=root/(stamp.strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid4().hex[:8]+'.json')
    path.write_text(encoded,encoding='utf-8')
    last=root/'news_acceptance_last.json'
    temporary=last.with_suffix('.json.'+uuid4().hex+'.tmp')
    temporary.write_text(encoded,encoding='utf-8');os.replace(temporary,last)
    return path


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
    if args.news:
        archived=archive_news_result(report)
        print('Haber ayrıntısı: '+str(archived))
    for row in report['checks']:print(row['check']+': '+row['state'])
    return 1 if any(r['state']=='failed' for r in report['checks']) else 0

if __name__=='__main__':raise SystemExit(main())
