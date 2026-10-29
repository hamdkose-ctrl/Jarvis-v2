"""UI bridge operations with explicit owning-runtime dependencies."""
from __future__ import annotations

class WebTasks:

    def team_snapshot(self) -> dict:
        from modules import team_center
        return team_center.snapshot(self._runtime._p().slug)

    def team_save(self, members: list, revision=None) -> list:
        from modules import team_center
        return team_center.save_members(self._runtime._p().slug, members, revision)

    def team_schedule(self, tasks: list, instruction: str, seconds: int=0, repeat_seconds: int=0, cron: str='') -> str:
        from modules import task_queue
        return task_queue.enqueue(self._runtime._p().slug, tasks, instruction, seconds, repeat_seconds, cron)

    def team_script_schedule(self, tasks: list, instruction: str='', cron: str='') -> str:
        """Schedule an explicit task DAG without a planner/model round-trip."""
        from modules import task_queue
        return task_queue.enqueue_script(self._runtime._p().slug, tasks, instruction, cron)

    def team_queue_run_now(self, identity: str) -> str:
        from modules import task_queue
        return task_queue.run_now(self._runtime._p().slug, identity)

    def team_queue_cancel(self, identity: str) -> bool:
        from modules import task_queue
        task_queue.cancel(self._runtime._p().slug, identity)
        return True

    def team_queue_edit(self, identity: str, operation: str, repeat_seconds=None) -> bool:
        from modules import task_queue
        return task_queue.configure(self._runtime._p().slug,identity,operation=operation,repeat_seconds=repeat_seconds)

    def team_control(self, kind: str, identity: str, action: str, control: str='', answer: str='', approval_id: str='') -> str:
        from modules import team_control_service
        profile = self._runtime._p()
        return team_control_service.dispatch(
            profile.slug, profile.name, self._runtime.engine.submit,
            kind, identity, action, control, answer, approval_id,
        )

    def team_verify(self, kind: str, identity: str) -> dict:
        from modules import team_verify_service
        return team_verify_service.verify(self._runtime._p().slug, kind, identity)

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

