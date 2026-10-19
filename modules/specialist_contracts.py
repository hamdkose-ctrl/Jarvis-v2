"""Concrete delivery contracts over the real adapters, not extra model employees."""
from __future__ import annotations
import importlib.util
import shutil
from modules import service_store,privacy

CONTRACTS={
 'research':('Kaynak URL, okuma kanıtı ve kaynakla sınırlı cevap','Genel web okuması; sayfa içeriğinin doğruluğu ayrıca değerlendirilir.'),
 'writer':('Gerçek kullanıcı dosyası ve SHA-256 özeti','Kaynaklara dayalı metin; olgu doğruluğu dosya varlığından çıkarılmaz.'),
 'media':('Gerçek video, boyut/süre/ses ve dosya özeti','Görsel içerik ve kaynak lisansı ayrıca kontrol edilir.'),
 'coder':('Bu göreve ait kod/test dosyaları, gerçek test günlüğü','Parolalı geliştirme alanı gerekir; kaynağa otomatik uygulama yok.'),
 'account':('Kullanıcıya ait servis anlık görüntüsü ve doğrulama kaydı','Bağlı ve yetkili mevcut hesabın izin verilen okuma işlemleri.'),
 'publish':('Somut hedef, mevcut izin/onay ve gönderim makbuzu','Uzman atanması dış gönderim izni vermez.'),
 'browser':('Gerçek sayfa durumu ve adım kanıtı','Etkili etkileşim mevcut tarayıcı onay kapısından geçer.'),
 'document':('Kaynak dosyası özeti; dönüşümde yeni çıktı dosyası','Dosya eksik/kesikse eksik bilgi başarı sayılmaz.'),
 'data':('Tarihli kaynak JSON veya değişmeyen CSV üzerinden hesap','Finans günlük kur/CSV; mağaza CSV; sosyal mevcut hesap okuması; haber kaynak başlıkları.'),
 'monitor':('Kullanıcıya ait takip kaydı, kalıcı görülen içerik ve kaynak alıntısı','Yalnız verilen kaynaklar; ilk tarama baz çizgisidir; Jarvis açıkken, model çağrısı olmadan çalışır.'),
 'capability':('Kaynak katalog referansı, belge erişim kanıtı veya onaylı sabit GET bağlantısı','API/MCP keşfi yetki/ücretsiz kullanım veya çalışan entegrasyon kanıtı değildir.'),
 'verify':('Önceki adımların teknik kanıt kontrolü','Teknik makbuz bütünlüğü, içeriğin anlamsal olarak doğru olduğu anlamına gelmez.'),
}


def describe(owner):
    service_store.identity(owner)
    from modules import team_center,developer
    from modules.goal_tools import LOCAL
    from modules.task_tools import CATALOG
    status=developer.status(owner)
    result=[]
    for member in team_center.members(owner):
        tools=[]
        for tool in member['tools']:
            delivery,scope=CONTRACTS.get(tool,('Adaptörün durumlu yerel sonucu','Mevcut adaptör izinleri çalışma sırasında denetlenir.'))
            readiness='runtime_check_required'
            if tool=='coder':readiness='unlocked' if status.get('enabled') or status.get('unlocked') else 'locked'
            elif tool=='media':readiness='local_prerequisites_present' if shutil.which('ffmpeg') and shutil.which('ffprobe') else 'missing_ffmpeg_or_ffprobe'
            elif tool in ('research','browser') and privacy.blocked('web'):readiness='privacy_blocked'
            elif tool=='writer':readiness='local_adapter_available'
            elif tool in ('data','monitor','capability'):readiness='adapter_available_connections_checked_per_operation'
            tools.append({'tool':tool,'registered':tool in LOCAL or tool in CATALOG,'deliverable':delivery,'scope':scope,'readiness':readiness})
        result.append({'id':member['id'],'name':member['name'],'tools':tools,'permissions_granted':False})
    return {'specialists':result,'limits':['Uzman kaydı yeni anahtar, hesap veya işlem yetkisi sağlamaz.',
        'Mağaza/banka yazma işlemleri ve dış MCP kod çalıştırma bu adaptörlerde yoktur.',
        'Bağlantı çalışırlığı yalnız gerçek operasyon sonucu ile doğrulanır.']}
