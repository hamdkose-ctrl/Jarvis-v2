"""Owner-run acceptance checks. Live accounts/desktop require explicit flags."""
import argparse
import json
from pathlib import Path
import platform
import re
from datetime import datetime,timezone
from modules.diagnostics import record_failure as _record_failure

def run(*,suite=True,gmail=False,desktop=False,narration=False):
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
        if gmail:
            def mail():
                from modules import account_tools
                result=account_tools.run(owner,{'service':'gmail','operation':'list_unread','limit':1})
                if result['state']!='done':return 'pending','Gmail read not available'
                items=result['snapshot']['items']
                if not items:return 'pending','No unread mail for attachment acceptance'
                result=account_tools.run(owner,{'service':'gmail','operation':'list_attachments','message_id':items[0]['id']})
                if result['state']!='done':return 'pending','Attachment list not available'
                supported=[r for r in result['snapshot']['items'] if r['supported']]
                if not supported:return 'pending','No supported attachment in the first unread mail'
                result=account_tools.run(owner,{'service':'gmail','operation':'read_attachment','message_id':items[0]['id'],
                                               'attachment_index':supported[0]['index']})
                from modules import task_results
                sealed=task_results.seal('account',result);task_results.verify(sealed,owner=owner)
                return 'passed','Read and verified; mail identity/body/attachment contents omitted'
            check('gmail_attachment',mail)
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
        for name in ('wake_word_microphone','screen_camera','speaker_voice_quality','other_live_accounts','restart_and_queue'):
            report['checks'].append({'check':name,'state':'pending','detail':'Manual acceptance required; not claimed by regression tests'})
    finally:llm._key_context.reset(token)
    return report

def main():
    parser=argparse.ArgumentParser(description='Jarvis V2 acceptance checks; no external sends or automatic source update')
    parser.add_argument('--gmail',action='store_true');parser.add_argument('--desktop',action='store_true')
    parser.add_argument('--narration',action='store_true');parser.add_argument('--skip-suite',action='store_true')
    parser.add_argument('--output',default='v2_kabul_sonucu.json')
    args=parser.parse_args();report=run(suite=not args.skip_suite,gmail=args.gmail,desktop=args.desktop,narration=args.narration)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in report['checks']:print(row['check']+': '+row['state'])
    return 1 if any(r['state']=='failed' for r in report['checks']) else 0

if __name__=='__main__':raise SystemExit(main())
