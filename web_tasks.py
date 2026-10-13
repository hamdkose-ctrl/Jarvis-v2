"""UI bridge operations with explicit owning-runtime dependencies."""
from __future__ import annotations

class WebTasks:

    def task_add(self, text: str, when: str='') -> dict:
        runtime = self._runtime
        return runtime.tasks.add(runtime._p(), text, when)

    def task_toggle(self, tid: int) -> bool:
        runtime = self._runtime
        runtime.tasks.toggle(runtime._p(), int(tid))
        return True

    def task_delete(self, tid: int) -> bool:
        runtime = self._runtime
        runtime.tasks.delete(runtime._p(), int(tid))
        return True

    def task_clear_done(self) -> int:
        runtime = self._runtime
        return runtime.tasks.clear_done(runtime._p())

    def note_add(self, text: str, photo_path: str='', title: str='') -> bool:
        runtime = self._runtime
        from modules import note_images
        note_images.add(runtime._p(), text, photo_path, title)
        return True

    def note_image(self, nid: int) -> str:
        runtime = self._runtime
        from modules import note_images
        return note_images.preview(runtime._p(), nid)

    def note_delete(self, nid: int) -> bool:
        runtime = self._runtime
        runtime._p().delete_note_item(int(nid))
        return True

    def event_add(self, title: str, when: str) -> dict:
        """when: 'YYYY-MM-DD' ya da 'YYYY-MM-DDTHH:MM'."""
        runtime = self._runtime
        if not runtime.re.match('^\\d{4}-\\d{2}-\\d{2}(T\\d{2}:\\d{2})?$', when or ''):
            raise ValueError('Tarih biçimi geçersiz')
        runtime.datetime.fromisoformat(when)
        if not title.strip():
            raise ValueError('Etkinlik başlığı gerekli')
        return runtime._p().add_event(title.strip(), when)

    def event_add_text(self, text: str, details: bool=False) -> str | dict:
        """'yarın 15'te toplantı' gibi serbest metinden etkinlik ekler."""
        runtime = self._runtime
        when, title = runtime.whenmod.parse_when(text, runtime.datetime.now())
        if not when:
            raise ValueError("Tarih ya da saat bulamadım. Örn: yarın 15'te toplantı")
        ev = runtime._p().add_event(title or text, when)
        return {**ev, 'label': f"{ev['title']} · {runtime.whenmod.describe(when)}"} if details else f"{ev['title']} · {runtime.whenmod.describe(when)}"

    def event_delete(self, eid: int) -> bool:
        runtime = self._runtime
        return runtime._p().delete_event(int(eid))
