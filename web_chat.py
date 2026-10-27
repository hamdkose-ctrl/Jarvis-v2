"""Chat page actions; dependencies are provided by the owning bridge."""
from __future__ import annotations

class WebChat:

    def development_status(self) -> dict:
        from modules import developer
        return developer.status(self._runtime._p().slug)

    def development_unlock(self, password: str) -> dict:
        from modules import developer
        return developer.unlock(self._runtime._p().slug, password)

    def development_enable(self) -> dict:
        from modules import developer
        previous = bool(self._runtime.engine.flags.get('mic', True))
        result = developer.enable(self._runtime._p().slug)
        if result.get('ok'):
            if not hasattr(self, '_development_previous_mic'):
                self._development_previous_mic = previous
            # Geliştirme ekranında sesli giriş ve uyandırma devre dışı;
            # yazı ve görsel ekleme kullanılmaya devam eder.
            self._runtime._set_mic(False)
        return result

    def development_disable(self) -> dict:
        from modules import developer
        result = developer.disable(self._runtime._p().slug)
        if result.get('ok'):
            if hasattr(self, '_development_previous_mic'):
                previous=self._development_previous_mic
                del self._development_previous_mic
                self._runtime._set_mic(previous)
        return result

    def development_password_change(self, old_password: str, new_password: str) -> dict:
        from modules import developer
        return developer.change_password(self._runtime._p().slug, old_password, new_password)

    def development_export(self) -> dict:
        from modules import developer
        return developer.export(self._runtime._p().slug)

    def recent(self, limit: int=40) -> list:
        """Bu oturumun son konuşmaları (motor günlüğü)."""
        runtime = self._runtime
        return [r for r in list(runtime.engine.event_log) if r.get('user') == runtime._p().name][-limit:]

    def continuity(self, device_id: str='', session_id: str='') -> dict:
        """Aktif kullanıcının Core-owned iş görünümünü bu istemci için salt-okunur döndürür."""
        from modules import continuity
        return continuity.snapshot(self._runtime._p().slug, device_id=device_id, session_id=session_id)

    def activity_clear(self) -> bool:
        """Canlı Aktivite geçmişini temizler; motorun normal loglarına dokunmaz."""
        runtime = self._runtime
        runtime.hub.activity.clear()
        runtime.hub.publish('activity', 'Aktivite ekranı temizlendi', 'info|Sistem|')
        return True

    def send(self, text: str, rid: str='') -> bool:
        runtime = self._runtime
        text = str(text).strip()
        accepted = runtime.engine.submit(text, 'yazı', runtime._p().name, rid=rid or None)
        if accepted is False:
            if text.replace('I', 'ı').replace('İ', 'i').lower().strip(' .!') in ('dur', 'sus', 'yeter', 'stop'):
                return False  # Immediate control: no assistant response will follow.
            raise ValueError('İstek kuyruğa alınmadı; boş veya daha önce gönderilmiş olabilir.')
        return True

    def history(self, query: str='', limit: int=300) -> list:
        runtime = self._runtime
        return runtime.history.read(runtime._p().slug, query or '', int(limit))

    def history_clear(self) -> bool:
        runtime = self._runtime
        runtime.history.clear(runtime._p().slug)
        self.chat_reset()
        return True

    def history_delete_conversation(self, day: str) -> dict:
        """Delete only the selected sidebar entry for the current user."""
        runtime = self._runtime
        owner = runtime._p()
        deleted_ids = set()
        with runtime.engine._event_lock:
            removed = runtime.history.delete_day(owner.slug, str(day), deleted_ids)
            runtime.engine.event_log[:] = [row for row in runtime.engine.event_log
                if not (row.get('user') == owner.name and row.get('hid') in deleted_ids)]
        from modules import chat_translation
        chat_translation._sources.pop(owner.slug, None)
        runtime.llm.reset_history(owner.slug)
        runtime.engine._sessions.for_owner(owner.slug).last_doc = None
        return {'ok': True, 'removed': removed}

    def chat_reset(self) -> bool:
        """Yeni sohbet: yazılı sohbetin kısa süreli hafızası sıfırlanır (kalıcı geçmiş silinmez)."""
        runtime = self._runtime
        from modules import chat_translation
        owner = runtime._p().slug
        with runtime.engine._event_lock:
            runtime.engine.requests_state.cancel(owner)
            chat_translation.reset(owner)
            runtime.llm.reset_history(owner)
            runtime.engine._sessions.reset(owner)
            runtime.engine._pending_photo.pop(owner, None)
        return True
