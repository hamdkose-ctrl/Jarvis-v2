"""Memory page actions; dependencies are provided by the owning bridge."""
from __future__ import annotations

class WebMemory:

    def goal_add(self, text: str) -> bool:
        runtime = self._runtime
        runtime._p().add_goal(text)
        return True

    def goal_delete(self, idx: int) -> bool:
        runtime = self._runtime
        return self._del('goals', idx)

    def fact_add(self, text: str) -> bool:
        runtime = self._runtime
        runtime._p().add_fact(text)
        return True

    def fact_delete(self, idx: int) -> bool:
        runtime = self._runtime
        return self._del('facts', idx)

    def fact_update(self, idx: int, expected: str, text: str) -> bool:
        return self._runtime._p().edit_fact(idx,expected,text)

    def rule_add(self, text: str) -> str:
        runtime = self._runtime
        from modules import learning
        return learning.add_rule(runtime._p(), str(text or ''))

    def rule_delete(self, idx: int) -> bool:
        runtime = self._runtime
        from modules import learning
        return learning.delete_rule(runtime._p(), int(idx))

    def pending_approve(self, idx: int=-1) -> int:
        runtime = self._runtime
        from modules import learning
        return learning.approve(runtime._p(), None if int(idx) < 0 else int(idx))

    def pending_reject(self, idx: int=-1) -> int:
        runtime = self._runtime
        from modules import learning
        return learning.reject(runtime._p(), None if int(idx) < 0 else int(idx))

    def physical_object_observe(self, object_id: str, label: str, location: str, source_device: str,
                                confidence: float, source: str, evidence_ref: str,
                                observed_at: str='', evidence_text: str='') -> dict:
        from modules import physical_memory
        return physical_memory.observe(
            self._runtime._p(), object_id=object_id, label=label, location=location,
            source_device=source_device, confidence=confidence, source=source,
            evidence_ref=evidence_ref, observed_at=observed_at, evidence_text=evidence_text)

    def physical_object_candidates(self) -> list[dict]:
        from modules import physical_memory
        return physical_memory.candidates(self._runtime._p())

    def physical_objects(self) -> list[dict]:
        from modules import physical_memory
        return physical_memory.confirmed(self._runtime._p())

    def physical_object_confirm(self, object_id: str) -> dict:
        from modules import physical_memory
        return physical_memory.confirm(self._runtime._p(), object_id)

    def physical_object_correct(self, object_id: str, label: str | None=None, location: str | None=None) -> dict:
        from modules import physical_memory
        return physical_memory.correct(self._runtime._p(), object_id, label=label, location=location)

    def physical_object_mark_not_seen(self, source_device: str, seen_object_ids: list[str], observed_at: str='') -> int:
        from modules import physical_memory
        if not isinstance(seen_object_ids, list):
            raise ValueError('seen_object_ids liste olmalı.')
        return physical_memory.mark_not_seen(self._runtime._p(), source_device=source_device,
                                             seen_object_ids=seen_object_ids, observed_at=observed_at)

    def learn_toggle(self, on: bool) -> bool:
        runtime = self._runtime
        runtime._p().set_pref('learn_from_chat', bool(on))
        return bool(on)

    def learning_report(self, fresh: bool=False) -> dict:
        runtime = self._runtime
        from modules import learning
        text = ''
        if not fresh and learning.REPORT_FILE.exists():
            try:
                text = learning.REPORT_FILE.read_text(encoding='utf-8')
            except OSError:
                text = ''
        if fresh or not text:
            text = learning.report()
        return {'text': text, 'ts': runtime.config.load_settings().get('last_learning_report') or ''}

    def _del(self, key: str, idx: int) -> bool:
        runtime = self._runtime
        lst = runtime._p().data.get(key, [])
        if 0 <= int(idx) < len(lst):
            lst.pop(int(idx))
            runtime._p().save()
            return True
        return False

    def contact_delete(self, name: str) -> bool:
        runtime = self._runtime
        c = runtime._p().data.get('contacts') or {}
        if name in c:
            c.pop(name)
            runtime._p().save()
            return True
        return False

    def contact_add(self, name: str, phone: str) -> str:
        runtime = self._runtime
        from modules import messaging
        from modules.personalization import display_name
        num = messaging.normalize_phone(phone or '')
        if not num:
            raise ValueError('Numarayı anlayamadım, 0532 123 45 67 gibi yaz.')
        name = ' '.join((display_name(w) for w in (name or '').split()))
        if not name:
            raise ValueError('Kişi adı boş olamaz.')
        runtime._p().data.setdefault('contacts', {})[name] = num
        runtime._p().save()
        return name

    def pref_set(self, key: str, value) -> bool:
        runtime = self._runtime
        if key in ('city', 'verbosity', 'voice', 'rate', 'language'):
            if value in ('', None):
                runtime._p().data['prefs'].pop(key, None)
                runtime._p().save()
            else:
                runtime._p().set_pref(key, value)
            if key == 'city':
                runtime.sampler.invalidate_weather()
            return True
        return False

    def macro_delete(self, key: str) -> bool:
        runtime = self._runtime
        m = runtime._p().data.get('macros') or {}
        if key in m:
            m.pop(key)
            runtime._p().save()
            return True
        return False

    def macro_run(self, key: str) -> bool:
        runtime = self._runtime
        owner = runtime._p()
        m = (owner.data.get('macros') or {}).get(key)
        if not m:
            return False
        return runtime.engine.submit(m.get('title', key), 'yazı', owner.name) is not False

    def kb_add_path(self, path: str) -> dict:
        runtime = self._runtime
        return runtime.kb.add(runtime._p(), path)

    def kb_remove(self, did: int) -> bool:
        runtime = self._runtime
        runtime.kb.remove(runtime._p(), int(did))
        return True

    def kb_clear(self) -> bool:
        runtime = self._runtime
        runtime.kb.clear(runtime._p())
        return True

    def kb_ask(self, question: str) -> str:
        runtime = self._runtime
        return runtime.kb.answer(runtime._p(), question)
