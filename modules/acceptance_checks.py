"""Owner-run acceptance checks. Live accounts/desktop require explicit flags."""
import argparse
import json
from pathlib import Path
import platform
import re
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

def run(*,suite=True,gmail=False,desktop=False,narration=False,public_data=False,video=False,
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
    from modules.manual_acceptance import CHECKS
    parser.add_argument('--confirm-manual',nargs='+',choices=CHECKS,default=[],help='Record only checks you personally completed on this PC')
    parser.add_argument('--reset-manual',nargs='+',choices=CHECKS,default=[],help='Forget previous manual declarations on this PC')
    parser.add_argument('--output',default='v2_kabul_sonucu.json')
    args=parser.parse_args();report=run(suite=not args.skip_suite,gmail=args.gmail,desktop=args.desktop,narration=args.narration,
        public_data=args.public_data,video=args.video,manual_confirm=args.confirm_manual,manual_reset=args.reset_manual)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in report['checks']:print(row['check']+': '+row['state'])
    return 1 if any(r['state']=='failed' for r in report['checks']) else 0

if __name__=='__main__':raise SystemExit(main())
