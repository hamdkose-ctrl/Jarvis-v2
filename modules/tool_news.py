"""Mevcut haber kaynak keşfinin salt okunur araç sözleşmesi."""
from modules.diagnostics import record_failure as _record_failure


def status():
    try:
        from modules import domain_tools
        if not callable(domain_tools.headlines):
            raise ValueError('Haber girişi bulunamadı.')
        return {'state': 'ready', 'detail': 'Haber okuma girişi mevcut; canlı kaynak sınanmadı.'}
    except Exception:
        _record_failure('modules/tool_news.py:status')
        return {'state': 'error', 'detail': 'Haber aracı bulunamadı.'}


def cancel():
    return {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'}


CONTRACT = {
    'id': 'news', 'name': 'Haber', 'area': 'iletisim', 'icon': 'globe',
    'actions': [{'id': 'headlines', 'name': 'Haber kaynakları',
                 'desc': 'Mevcut domain_tools.headlines kaynak okuması; başlıklar içerik kanıtı değildir.',
                 'class': 'read', 'params': {'url': 'str', 'query': 'str'}}],
    'status': status, 'cancel': cancel,
}
