"""Focused Live component; receives the current Live instance and service adapters.

No second session, worker thread, user identity or request identity is created here.
Compatibility delegates remain on Live; calls keep the existing request guards.
"""
from __future__ import annotations

def flush_user(self, services) -> None:
    if self._in_buf:
        text = ' '.join((t.strip() for t in self._in_buf if t.strip())).strip()
        self._in_buf = []
        if text:
            from modules import stt_guard
            why = stt_guard.reject(text)
            if why:
                # Gürültüden uydurulan yabancı söz ya da Jarvis'in kendi sesinin yankısı: sohbete/işleme geçmez.
                services.log.info('Duyulan söz atıldı (%s): %d karakter', 'yabancı/gürültü' if why == 'foreign' else 'yankı', len(text))
                return
            fixed = services.apply_fixes(text)
            services.log.info('İşlem kaydı: %s', 'modules/live.py:_flush_user')
            self._recent_user.append(text)
            self._convo.append(('user', fixed))
            self.emit('user', fixed, 'ses')

def flush_transcripts(self, services) -> str:
    """Biriken konuşma yazılarını arayüze/loga aktarır; Jarvis'in bu turda söylediğini döndürür."""
    heard = bool(self._in_buf)
    self._flush_user()
    if self._out_buf:
        text = ''.join(self._out_buf).strip()
        self._out_buf = []
        if text:
            from modules import stt_guard
            stt_guard.note_said(text)
            services.log.info('İşlem kaydı: %s', 'modules/live.py:_flush_transcripts')
            if self._suppress_output_turns > 0:
                self._suppress_output_turns -= 1
                services.log.info('Live ses transkripti arayüzde yinelenmedi (yazılı cevap zaten gösterilmişti)')
            else:
                self._convo.append(('assistant', text))
                self.emit('assistant', text, 'ses')
        return text
    if heard and (not self._tools_running):
        services.log.info('Jarvis bu söze cevap vermedi (sessiz kaldı)')
    return ''
