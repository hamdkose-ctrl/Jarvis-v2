"""Focused Live component; receives the current Live instance and service adapters.

No second session, worker thread, user identity or request identity is created here.
Compatibility delegates remain on Live; calls keep the existing request guards.
"""
from __future__ import annotations
import asyncio
import re
import time
from modules.diagnostics import record_failure as _record_failure

async def run(self, session, fc, services) -> None:
    from google.genai import types
    args = dict(fc.args or {})
    _tool_names = {'uygulama_ac': 'Uygulama açma', 'muzik_cal': 'Müzik', 'komut': 'Jarvis aracı', 'gorev_ekle': 'Görev', 'ses_degistir': 'Ses ayarı', 'kural_ogren': 'Öğrenme', 'yanlis_duyma': 'Ses düzeltme'}
    area = _tool_names.get(fc.name, fc.name.replace('_', ' ').title())
    from modules import privacy
    safe_args = privacy.redact(', '.join((f'{k}={str(v)[:90]}' for k, v in args.items())), force=True)
    self.emit('activity', f'{area} başlatıldı', f'working|{area}|{safe_args}')
    try:
        if fc.name == 'ses_degistir':
            result = await self._direct_tool(self._change_voice, str(args.get('ses') or ''))
        elif fc.name == 'kural_ogren':
            services.log.info('İşlem kaydı: %s', 'modules/live.py:_run_tool')
            kural = ' '.join(str(args.get('kural') or '').split())
            if kural:
                from modules import learning
                if learning.is_time_reminder_rule(kural):
                    result = 'Bu zamana bağlı bir hatırlatma; kalıcı kural kaydetmedim. hatirlatma_ekle aracını kullan ve gün/saat yoksa kullanıcıya sor.'
                else:
                    result = await asyncio.get_running_loop().run_in_executor(None, self.handler, f'kural ekle: {kural}')
            else:
                result = 'Geçersiz istek: kural boş. Kullanıcıya ne öğretmek istediğini sor.'
        elif fc.name == 'yanlis_duyma':
            self._flush_user()
            wrong = self._recent_user[-2] if len(self._recent_user) >= 2 else ''
            services.log.info('İşlem kaydı: %s', 'modules/live.py:_run_tool')
            from modules import learning
            result = await self._direct_tool(learning.learn_mishearing, wrong, str(args.get('dogru') or ''))
        elif fc.name == 'muzik_cal':
            services.log.info('İşlem kaydı: %s', 'modules/live.py:_run_tool')
            self._flush_user()
            last_user = ' '.join((self._recent_user[-1] if self._recent_user else '').strip().split())
            last_norm = last_user.casefold().replace("'", '').replace('’', '').strip(' .!?…')
            if re.fullmatch('(?:youtube|youtubeu)\\s+(?:aç|ac|başlat|baslat|çalıştır|calistir)', last_norm):
                result = await asyncio.get_running_loop().run_in_executor(None, self.handler, 'YouTube aç')
                services.log.info('İşlem kaydı: %s', 'modules/live.py:_run_tool')
            else:
                result = await self._direct_tool(services._play_music, args)
        elif fc.name == 'gorev_ekle' and services._task_place(args) is not None:
            services.log.info('İşlem kaydı: %s', 'modules/live.py:_run_tool')
            result = await self._direct_tool(services._add_handoff, args)
        else:
            req = services._build_request(fc.name, args)
            if req is None:
                result = 'Geçersiz istek: eksik ya da anlaşılmayan bilgi var. Kullanıcıya tekrar sor.'
            else:
                if fc.name != 'komut':
                    services.log.info('İşlem kaydı: %s', 'modules/live.py:_run_tool')
                result = await asyncio.get_running_loop().run_in_executor(None, self.handler, req)
    except Exception as exc:
        _record_failure('modules/live.py:_run_tool')
        result = f'Yapamadım: {exc}'
    finally:
        self._tools_running = max(0, self._tools_running - 1)
    if self.wants_sleep():
        self._sleep_after = True
    result = str(result or 'Bir yanıt alamadım.')[:services.TOOL_RESULT_MAX]
    services.log.info('İşlem kaydı: %s', 'modules/live.py:_run_tool')
    _bad = result.casefold().startswith(('yapamadım', 'hata', 'başarısız', 'bulamadım')) or 'bulunamadı' in result.casefold()
    self.emit('activity', f'{area} başarısız' if _bad else f'{area} tamamlandı', f"{('error' if _bad else 'done')}|{area}|{privacy.redact(result[:500], force=True)}")
    self._activity = time.monotonic()
    try:
        await session.send_tool_response(function_responses=[types.FunctionResponse(id=fc.id, name=fc.name, response={'sonuc': result})])
    except Exception:
        _record_failure('modules/live.py:_run_tool')
        services.log.warning('Araç sonucu gönderilemedi (oturum kapandı)')

async def direct(self, fn, *args, services):
    if self.prepare_tool is None:
        raise RuntimeError('Canlı araç için kullanıcı ve iptal bağlamı kurulmamış.')
    run = self.prepare_tool(fn, *args)
    return await asyncio.get_running_loop().run_in_executor(None, run)

def change_voice(self, name: str, services) -> str:
    match = next((v for v in services.VOICES if v.lower() == name.strip().lower()), None)
    if match is None:
        return 'Böyle bir ses yok. Geçerli sesler: ' + ', '.join(services.VOICES)
    if match == services.voice_name():
        return f'Zaten {match} sesi seçili. Bu sesle devam ediyorum; yeniden değiştirmedim.'
    from config import save_settings
    save_settings(live_voice=match)
    self._voice_confirmation = match
    self._voice_transition = True
    self._reload_at = time.monotonic() + 0.3
    self._reload = True
    return f'{match} sesine geçiş hazırlanıyor. Bu oturumda değişiklik onayı söyleme; yeni oturum söyleyecek.'
