"""Read-only local prerequisites; no network, OAuth refresh or setting changes."""
from pathlib import Path
import json
import shutil
import sys
from config import DATA_DIR
from modules import service_store, publish_services


def _file(path):
    return not any(p.is_symlink() for p in (path,*path.parents)) and path.is_file()


def report(owner):
    service_store.identity(owner)
    lines=['Yerel kurulum kontrolü; canlı bağlantı ve izin geçerliliği doğrulanmadı.']
    legacy_owner=None
    settings=DATA_DIR/'settings.json'
    try:
        if _file(settings) and settings.stat().st_size<=64000:
            saved=json.loads(settings.read_text(encoding='utf-8'))
            if isinstance(saved,dict):legacy_owner=saved.get('google_legacy_owner')
    except (OSError,ValueError):pass
    for label,name in [('Gmail okuma','google_token.json'),('Gmail gönderim','google_gmail_write_token.json'),
                       ('YouTube okuma','google_youtube_read_token.json'),('YouTube yayın','google_youtube_write_token.json'),
                       ('YouTube yorum','google_youtube_reply_write_token.json')]:
        state=('kullanıcı OAuth dosyası mevcut; süre/kapsam doğrulanmadı.' if _file(DATA_DIR/'google_users'/owner/name) else
               'bu kullanıcıya atanmış eski OAuth dosyası mevcut; Google bağlantısı açıldığında kullanıcı alanına taşınabilir. Süre/kapsam doğrulanmadı.' if legacy_owner==owner and _file(DATA_DIR/name) else
               'kullanıcı OAuth dosyası yok; bağlantı izni gerekli.')
        lines.append(label+': '+state)
    configs={}
    for service,label,fields in [('telegram','Telegram',('bot_token','read_chat_id')),('whatsapp','WhatsApp',('access_token','api_version','phone_number_id')),
                                 ('instagram','Instagram',('access_token','api_version','ig_user_id')),('media_voice','Yerel anlatım',())]:
        try:
            config=publish_services.configuration(owner,service)
        except PermissionError:
            config={};state='yapılandırma yok.'
        except (ValueError,OSError):
            config={};state='yapılandırma okunamadı veya geçersiz.'
        else:
            missing=[k for k in fields if not isinstance(config.get(k),str) or not config[k].strip()]
            state='eksik alanlar: '+', '.join(missing) if missing else 'yerel alanlar mevcut; canlı doğrulanmadı.'
        configs[service]=config;lines.append(label+': '+state)
    wa=configs['whatsapp']
    webhook=wa.get('webhook_enabled') is True and all(isinstance(wa.get(k),str) and len(wa[k])>=16 for k in ('app_secret','verify_token')) and isinstance(wa.get('phone_number_id'),str) and wa['phone_number_id'].isdigit()
    lines.append('WhatsApp webhook: '+('yerel ayarlar mevcut; HTTPS ve çalışan dinleyici doğrulanmadı.' if webhook else 'kapalı veya ayarlar eksik.'))
    lines.append('WhatsApp maliyet yetkisi: '+('açık.' if wa.get('allow_service_costs') is True else 'kapalı.'))
    lines.append('Telegram güncelleme tüketimi: '+('açık.' if configs['telegram'].get('consume_updates') is True else 'kapalı.'))
    for name in ('ffmpeg','ffprobe'):
        lines.append(name+': '+('PATH içinde mevcut; çalışması denenmedi.' if shutil.which(name) else 'bulunamadı.'))
    voice=configs['media_voice'];value=voice.get('model','');model=Path(value) if isinstance(value,str) else Path('.')
    backend=voice.get('backend','auto')
    piper=shutil.which('piper') and model.suffix.lower()=='.onnx' and _file(model)
    state=('Piper ve model mevcut; ses üretimi denenmedi.' if piper and backend in ('auto','piper') else
           'Windows SAPI seçilebilir; paketleri ve ses üretimi denenmedi.' if sys.platform=='win32' and backend in ('auto','sapi') else
           'yerel motor/model eksik veya seçim geçersiz; buluta geçilmez.')
    lines.append('Anlatım: '+state)
    lines.append('Gönderim için kesin hedef yetkisi ayrıca gerekir. Kontrol ağ çağrısı yapmaz, ayar veya yetki değiştirmez.')
    return '\n'.join(lines)
