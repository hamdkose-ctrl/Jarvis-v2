"""Versioned local tool contracts. Metadata describes risk; it grants no permission."""
import copy
import re

VERSION = 1
CATALOG = {
    'media': {'risk':'local_media_create','replay_safe':True,'required':('image','image_sha256'),
              'optional':('audio','audio_sha256','duration','scenes','layout','narration')},
    'publish': {'risk': 'external_publish', 'replay_safe': False,
                'required': ('service','destination'), 'optional': ('text','subject','file','file_sha256','privacy','image_url','source_task','video_url','media_type','operation','parent_id','text_from_task')},
    'account': {'risk': 'account_read', 'replay_safe': True,
                'required': ('service', 'operation'), 'optional': ('limit', 'message_id', 'index','resource_id','query','file_id','cell_range','thread_id','window_start','window_end','minutes')},
    'research': {'risk': 'network_read', 'replay_safe': True,
                 'required': (), 'optional': ('url', 'query', 'question')},
    'file': {'risk': 'local_evidence_read', 'replay_safe': True,
             'required': ('path', 'operation'), 'optional': ()},
    'finance': {'risk': 'local_evidence_read', 'replay_safe': True,
                'required': ('operation', 'payload'), 'optional': ()},
    'computer': {'risk': 'local_evidence_read', 'replay_safe': True,
                 'required': ('app', 'operation'), 'optional': ()},
    'writer': {'risk': 'local_file_create', 'replay_safe': True,
               'required': ('instruction',), 'optional': ('filename',)},
    'browser': {'risk': 'external_effect_possible', 'replay_safe': False,
                'required': ('url', 'instruction'), 'optional': ('mode',)},
    'coder': {'risk': 'development_workspace', 'replay_safe': False,
              'required': ('request',), 'optional': ()},
    'verify': {'risk': 'local_evidence_read', 'replay_safe': True,
               'required': (), 'optional': ()},
}


def validate_input(kind, data, *, complete=True):
    if not isinstance(kind, str) or kind not in CATALOG:
        raise ValueError('Araç yeteneği geçersiz.')
    spec = CATALOG[kind]
    if kind == 'media':
        from modules import media_tools
        return media_tools.validate(data)
    if kind == 'publish':
        from modules import publish_services
        return publish_services.validate(data)
    if kind == 'account':
        from modules import account_tools
        # Account schema includes an integer limit; it is not a text-only worker.
        return account_tools.validate_input(data)
    if kind == 'computer':
        from modules import computer_worker_contract
        if not isinstance(data, dict) or set(data) != {'app', 'operation'}:
            raise ValueError('ComputerWorker girdisi geçersiz.')
        computer_worker_contract.capability(data['app'], data['operation'])
        return copy.deepcopy(data)
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or key not in spec['required'] + spec['optional']
        for key in data
    ):
        raise ValueError('Araç girdisi desteklenmeyen alan içeriyor.')
    if complete and any(key not in data for key in spec['required']):
        raise ValueError('Araç için gerekli girdi eksik: ' + kind)
    # Planner pre-validation intentionally permits incomplete tool drafts; the
    # worker-side validation below is the execution boundary.
    if complete and kind == 'research' and (bool(data.get('url')) == bool(data.get('query'))):
        raise ValueError('Araştırma için tam olarak bir URL veya sorgu gerekli.')
    for key, value in data.items():
        limit = 2048 if key in ('url', 'query') else 120 if key == 'filename' else 20000
        if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
            raise ValueError('Araç girdi alanı geçersiz: ' + key)
    if 'url' in data:
        from modules.browser_agent import _url
        _url(data['url'])
    if 'filename' in data and not re.fullmatch(r'[\w-]{1,80}\.md', data['filename']):
        raise ValueError('Rapor adı basit bir .md dosyası olmalı.')
    return copy.deepcopy(data)


def execution(owner, job_id, task):
    """Derive identity and policy from the runtime, never from model input."""
    spec = CATALOG[task['agent']]
    return {'version': VERSION, 'owner': owner, 'job_id': job_id,
            'task_id': task['id'], 'capability': task['agent'],
            'risk': spec['risk'], 'replay_safe': spec['replay_safe'],
            'attempt': task.get('attempts', 0), 'outcome': 'pending'}


def outcome(kind, state):
    if state == 'done':
        return 'verified'
    if state == 'approval':
        return 'approval_required'
    if state in ('blocked', 'unavailable'):
        return state
    return 'failed' if CATALOG[kind]['replay_safe'] else 'effect_unknown'
