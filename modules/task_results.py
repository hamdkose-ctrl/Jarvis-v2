"""Local evidence checks for durable task outputs; no model or service calls."""
from pathlib import Path
import hashlib
import re
import math
from modules import outcome_contracts

VERSION = 1
STATES = {'done', 'failed', 'blocked', 'approval', 'unavailable'}


def browser_readonly_receipt(output):
    """A local read-only observation receipt, never a remote effect approval.

    Only the exact native goto/read steps and observed page are included;
    this cannot be used to authorize click/fill/send or replay an effect.
    """
    import json
    if not isinstance(output, dict) or output.get('readonly') is not True:
        raise ValueError('Only completed readonly browser observations have local receipts.')
    if (not isinstance(output.get('page'), dict)
            or not isinstance(output.get('steps'), list)
            or not output['steps']):
        raise ValueError('Readonly browser page/step evidence missing.')
    payload = json.dumps(
        {'steps': output['steps'], 'page': output['page']},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')
    if len(payload) > 1024 * 1024:
        raise ValueError('Readonly browser evidence too large.')
    return {'service': 'browser_readonly_observation',
            'remote_id': hashlib.sha256(payload).hexdigest()}


def file_digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError('Kanıt dosyası eksik, boş veya sembolik bağ.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def check(kind, output):
    if not isinstance(output, dict) or output.get('state') != 'done':
        raise ValueError('Görev sonucu tamamlanmış değil.')
    if kind in ('research', 'writer', 'coder'):
        if not isinstance(output.get('text'), str) or not output['text'].strip():
            raise ValueError('Görev çıktısı boş.')
    if kind == 'research':
        from modules.browser_agent import _url
        _url(output.get('source', ''))
        chars = output.get('source_chars')
        if type(chars) is not int or chars < 80:
            raise ValueError('Araştırmanın kaynak okuma kanıtı eksik.')
        if 'source_claims' in output:
            from modules import research_evidence
            claims=output['source_claims']
            if not isinstance(claims,list) or len(claims)>10:raise ValueError('Araştırma claim kaydı geçersiz.')
            for claim in claims:
                if (not isinstance(claim,dict) or any(not isinstance(claim.get(key),str) for key in
                        ('subject','scope','as_of','value','url','evidence'))):
                    raise ValueError('Araştırma claim alanları geçersiz.')
                _url(claim['url'])
                import json
                if research_evidence.parse_value_quote(json.dumps({'value':claim['value'],'quote':claim['evidence']}),claim['evidence']) is None:
                    raise ValueError('Araştırma claim değeri kaynak alıntısıyla uyuşmuyor.')
        if output.get('news_article'):
            from modules import research_evidence
            research_evidence.news_receipt(output)
        if output.get('event_evidence'):
            from modules import news_temporal
            news_temporal.event_receipt(output)
    elif kind == 'writer':
        digest = output.get('sha256', '')
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Raporun içerik özeti eksik.')
        if file_digest(output.get('file', '')) != digest:
            raise ValueError('Rapor dosyası değişmiş veya eksik.')
        if 'news_report_evidence' in output:
            from modules import research_evidence
            evidence=output['news_report_evidence']
            expected=research_evidence.news_report(evidence['sources'])+research_evidence.unavailable_footer(evidence['unavailable'])
            if output['text']!=expected or Path(output['file']).read_text(encoding='utf-8')!=expected:
                raise ValueError('Haber raporu tarih, kaynak ve alıntı kaydıyla eşleşmiyor.')
    elif kind == 'coder':
        if output.get('draft') is not True or output.get('test_ok') is not True:
            raise ValueError('Kod taslağı ve geçerli başarılı test kanıtı gerekli.')
        files=output.get('files')
        if not isinstance(files,list) or not files or not isinstance(output.get('owner'),str) or not output['owner']:
            raise ValueError('Kod teslim dosyaları ve sahibi eksik.')
        if any(not isinstance(item,dict) or file_digest(item.get('file',''))!=item.get('sha256') for item in files):
            raise ValueError('Kod teslim dosyası değişmiş veya eksik.')
        if output.get('file')!=files[0]['file'] or file_digest(output.get('test_log',''))!=output.get('test_log_sha256'):
            raise ValueError('Kod teslimi veya test günlüğü değişmiş.')
        # The Scheduler's write-ahead receipt must identify the SAME verified
        # test log, not an arbitrary successful-looking local artifact.
        # Historical legacy coder outputs without a receipt remain readable.
        if 'receipt' in output and output['receipt'] != {
                'service': 'coder_draft', 'remote_id': output['test_log_sha256']}:
            raise ValueError('Kod taslağı receipt kimliği test günlüğüyle eşleşmiyor.')
    elif kind == 'finance':
        import json
        from modules import finance_readonly
        allowed = {'normalize_ohlcv','compare_equities','portfolio_summary','dcf',
                   'comparable_companies','lbo','trade_plan_draft',
                   'trade_plan_risk_checklist','trade_plan_risk_decision'}
        if (output.get('operation') not in allowed
                or output.get('disclaimer') != finance_readonly.NOT_INVESTMENT_ADVICE
                or output.get('text') !=
                   'Finans salt-okunur analizi tamamlandı. ' + finance_readonly.NOT_INVESTMENT_ADVICE):
            raise ValueError('FinanceWorker readonly operation or disclaimer invalid.')
        try:
            encoded = json.dumps(output['analysis'], allow_nan=False, sort_keys=True)
            if len(encoded) > 500_000:
                raise ValueError('FinanceWorker result exceeds evidence bound.')
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError('FinanceWorker result is not JSON evidence.') from exc
    elif kind == 'computer':
        from modules import computer_worker_contract
        observation = output.get('observation')
        receipt = output.get('receipt')
        if not isinstance(observation, dict) or not isinstance(receipt, dict):
            raise ValueError('ComputerWorker receipt/observation missing.')
        capability = receipt.get('capability')
        if not isinstance(capability, dict):
            raise ValueError('ComputerWorker capability missing.')
        granted = computer_worker_contract.capability(
            capability.get('app'), capability.get('operation'),
        )
        elements = observation.get('elements')
        if (not isinstance(observation.get('window'), dict)
                or not isinstance(elements, list)
                or computer_worker_contract.measure_uia(elements) !=
                    {key: observation.get(key) for key in ('state','elements','count')}
                or receipt != computer_worker_contract.receipt(
                    receipt.get('job_id'), granted, 'observed', evidence=observation,
                )):
            raise ValueError('ComputerWorker UIA readback receipt mismatch.')
    elif kind == 'browser':
        steps = output.get('steps')
        if not isinstance(steps, list) or not steps or any(
            not isinstance(step, dict) or step.get('verified') is not True for step in steps
        ):
            raise ValueError('Tarayıcı adımlarının doğrulama kanıtı eksik.')
        page = output.get('page')
        if not isinstance(page, dict):
            raise ValueError('Tarayıcı sayfa kaydı eksik.')
        from modules.browser_agent import _url
        _url(page.get('url', ''))
        if output.get('readonly') is True:
            if (output.get('image') or output.get('image_sha256')
                    or any(step.get('op') not in ('goto','read') for step in steps)):
                raise ValueError('Read-only browser evidence contains an effect.')
            if output.get('receipt') != browser_readonly_receipt(output):
                raise ValueError('Read-only browser observation receipt mismatch.')
        else:
            digest = file_digest(output.get('image', ''))
            if output.get('image_sha256') != digest:
                raise ValueError('Tarayıcı ekran dosyası değişmiş veya kanıt özeti eksik.')
    elif kind == 'verify':
        checks = output.get('checks')
        if not isinstance(checks, dict) or not checks or any(v is not True for v in checks.values()):
            raise ValueError('Bağımlı sonuçların doğrulama kanıtı eksik.')
    elif kind == 'account':
        from modules import account_tools
        snapshot = output.get('snapshot')
        if isinstance(snapshot,dict) and snapshot.get('service') in ('telegram','youtube','instagram','whatsapp'):
            from modules import social_reads
            service=snapshot['service'];items=snapshot.get('items')
            if snapshot.get('operation') not in account_tools.SERVICES[service]['operations'] or snapshot.get('scope')!='bounded_account_read':raise ValueError('Sosyal okuma kapsamı geçersiz.')
            if not isinstance(snapshot.get('owner'),str) or not snapshot['owner'] or type(snapshot.get('fetched_at')) not in (int,float) or not math.isfinite(snapshot['fetched_at']) or snapshot['fetched_at']<=0:raise ValueError('Sosyal okuma kimliği/zamanı eksik.')
            if not isinstance(items,list) or len(items)>20 or any(not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'] or not isinstance(item.get('text'),str) for item in items):raise ValueError('Sosyal okuma kanıtı geçersiz.')
            if output.get('sha256')!=account_tools.digest(snapshot) or output.get('text')!=social_reads.render(snapshot):raise ValueError('Sosyal okuma kaydı değişmiş.')
            return True
        if not isinstance(snapshot, dict) or snapshot.get('service') != 'gmail' or snapshot.get('operation') not in ('list_unread', 'read_message','list_attachments','read_attachment'):
            raise ValueError('Hesap sonucu desteklenen okumaya ait değil.')
        if not isinstance(snapshot.get('owner'), str) or not snapshot['owner']:
            raise ValueError('Hesap sonucu kullanıcı kaydı eksik.')
        if snapshot['operation'] in ('list_attachments','read_attachment'):
            from modules import mail_attachments
            mail_attachments.verify(snapshot)
            if output.get('sha256')!=account_tools.digest(snapshot) or output.get('text')!=account_tools.render_snapshot(snapshot):raise ValueError('Ek okuma kaydı değişmiş.')
            return True
        if snapshot['operation'] == 'read_message':
            from modules import mail_content
            item = snapshot.get('message')
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', item['id']):
                raise ValueError('Mail kimlik kanıtı eksik.')
            if any(not isinstance(item.get(key), str) for key in ('from', 'subject', 'body')) or not item['body'].strip() or len(item['body']) > mail_content.MAX_TEXT:
                raise ValueError('Mail gövde kanıtı geçersiz.')
            if type(item.get('truncated')) is not bool or item.get('format') not in ('plain', 'html_text'):
                raise ValueError('Mail okuma kapsamı eksik.')
            ts = snapshot.get('fetched_at')
            if type(ts) not in (int, float) or not math.isfinite(ts) or ts <= 0:
                raise ValueError('Mail okuma zamanı eksik.')
            if output.get('sha256') != account_tools.digest(snapshot) or output.get('text') != account_tools.render_snapshot(snapshot):
                raise ValueError('Mail gövde kaydı değişmiş.')
            return True
        limit = snapshot.get('limit')
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('Hesap sonucu liste sınırı geçersiz.')
        items = snapshot.get('items')
        if not isinstance(items, list) or len(items) > limit or any(
            not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']
            or any(not isinstance(item.get(key), str) for key in ('from', 'subject')) for item in items
        ):
            raise ValueError('Hesap mesaj kanıtı geçersiz.')
        if len({item['id'] for item in items}) != len(items):
            raise ValueError('Hesap mesaj kimlikleri tekil olmalı.')
        if type(snapshot.get('fetched_at')) not in (int, float) or not math.isfinite(snapshot['fetched_at']) or snapshot['fetched_at'] <= 0 or snapshot.get('query') != 'is:unread in:inbox' or type(snapshot.get('has_more')) is not bool:
            raise ValueError('Hesap okuma kaydı eksik.')
        if 'show_ids' in snapshot and type(snapshot['show_ids']) is not bool:
            raise ValueError('Mail kimlik gösterimi geçersiz.')
        if output.get('sha256') != account_tools.digest(snapshot):
            raise ValueError('Hesap okuma kaydı değişmiş.')
        if output.get('text') != account_tools.render_snapshot(snapshot):
            raise ValueError('Hesap sonuç metni okuma kaydıyla eşleşmiyor.')
    elif kind == 'publish':
        receipt=output.get('receipt')
        if not isinstance(receipt,dict) or receipt.get('scope')!='provider_accepted' or not isinstance(receipt.get('remote_id'),str) or not receipt['remote_id']:
            raise ValueError('Gerçek servis işlem kimliği eksik.')
        from modules import publish_services
        if receipt.get('service') not in publish_services.OPERATIONS or not isinstance(receipt.get('destination'),str):
            raise ValueError('Servis/hedef kanıtı eksik.')
        if not isinstance(output.get('payload_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',output['payload_sha256']):
            raise ValueError('Gönderim içerik kaydı eksik.')
    elif kind == 'file':
        # Read-only extraction must prove the SAME allowed file is still
        # present with the same bytes before Core can accept WorkerResult.
        from modules import file_worker
        evidence = output.get('file_evidence')
        if (not isinstance(evidence, dict)
                or evidence.get('reason_code') != 'OK'
                or not isinstance(evidence.get('path'), str)
                or not isinstance(evidence.get('identity'), str)
                or not isinstance(evidence.get('digest'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', evidence['digest'])
                or not isinstance(evidence.get('locations'), list)
                or not isinstance(evidence.get('warnings'), list)
                or not isinstance(output.get('obligations'), list)):
            raise ValueError('Dosya okuma kimlik/içerik kanıtı eksik.')
        source = Path(evidence['path'])
        if (source.is_symlink() or not source.is_file()
                or source.suffix.lower() not in file_worker.docs.SUPPORTED
                or not file_worker._is_within_allowed(source)
                or str(source.resolve()) != evidence['identity']
                or file_worker.content_digest(source) != evidence['digest']):
            raise ValueError('Dosya kaynağı, izin kökü veya digest değişmiş.')
        if (len(evidence['locations']) > file_worker.MAX_LOCATIONS
                or any(not isinstance(row, dict)
                       or set(row) != {'page', 'line', 'sheet', 'cell_or_range'}
                       or any(value is not None and not isinstance(value, (str, int))
                              for value in row.values())
                       for row in evidence['locations'])
                or any(not isinstance(item, str) for item in evidence['warnings'])):
            raise ValueError('Dosya okuma konum kanıtı geçersiz.')
    elif kind == 'media':
        from modules import media_tools
        if file_digest(output.get('file',''))!=output.get('sha256'):raise ValueError('Video dosyası değişmiş.')
        if media_tools.probe(output['file'])!=output.get('media'):raise ValueError('Video akış kanıtı değişmiş.')
    else:
        raise ValueError('Bilinmeyen sonuç türü.')
    return True


def seal(kind, output):
    if not isinstance(output, dict) or output.get('state') not in STATES:
        raise ValueError('Araç geçerli bir görev sonucu döndürmedi.')
    output = dict(output)
    if output['state'] == 'done':
        if kind == 'browser' and output.get('readonly') is not True:
            output['image_sha256'] = file_digest(output.get('image', ''))
        output = outcome_contracts.attach(kind, output)
        check(kind, output)
        outcome_contracts.validate_metadata(kind, output, legacy_ok=False)
        output['verification'] = {'version': VERSION, 'agent': kind, 'scope': 'execution_evidence',
                                  'outcome': output['outcome_contract']['id']}
    return output


def verify(output, owner=None, *, expected_kind=None):
    metadata = output.get('verification', {}) if isinstance(output, dict) else {}
    if not isinstance(metadata, dict) or metadata.get('version') != VERSION:
        raise ValueError('Sonucun doğrulama kaydı eksik; eski kayıt başarı kanıtı olarak kullanılamaz.')
    if metadata.get('scope')!='execution_evidence' or (expected_kind is not None and metadata.get('agent')!=expected_kind):
        raise ValueError('Sonucun beklenen worker türü veya kanıt kapsamı eşleşmiyor.')
    checked = check(metadata.get('agent'), output)
    if metadata.get('outcome') is not None:
        outcome_contracts.validate_metadata(metadata.get('agent'), output, legacy_ok=False)
        if metadata['outcome'] != output['outcome_contract']['id']:
            raise ValueError('Doğrulama kaydı sonuç sözleşmesiyle eşleşmiyor.')
    if owner is not None and metadata.get('agent') == 'coder' and output.get('owner') != owner:
        raise PermissionError('Kod sonucu farklı kullanıcıya ait.')
    if owner is not None and metadata.get('agent') == 'account' and output.get('snapshot', {}).get('owner') != owner:
        raise PermissionError('Hesap sonucu farklı kullanıcıya ait.')
    if owner is not None and metadata.get('agent') == 'publish':
        from modules import outbox
        saved=outbox.get(owner,output.get('id'))
        if saved['state']!='accepted' or saved['receipt']!=output['receipt'] or saved['digest']!=output['payload_sha256']:
            raise ValueError('Gönderim kanıtı kalıcı servis kaydıyla eşleşmiyor.')
    return checked
