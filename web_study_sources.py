"""Study sources API actions with explicit injected services."""
import re


class WebStudySources:

    def study_math(self, question: str='', attachment_path: str='', selection=None) -> dict:
        from modules import math_tutor
        return math_tutor.solve(self._study_dependencies.current_profile(), str(question), str(attachment_path), selection)

    def study_math_preview(self, page: int=1) -> dict:
        from modules import math_tutor
        return math_tutor.preview(self._study_dependencies.current_profile(), page)

    def study_source_preview(self, doc_id: int=0, page: int=1) -> dict:
        from modules import study_preview
        return study_preview.source(self._study_dependencies.current_profile(), int(doc_id), page)

    def study_source_restore_original(self, doc_id: int, path: str) -> dict:
        from modules import study_preview
        return study_preview.restore_original(self._study_dependencies.current_profile(), int(doc_id), str(path))

    def study_math_clear(self) -> bool:
        from modules import math_tutor
        return math_tutor.clear(self._study_dependencies.current_profile())

    def study_status(self) -> dict:
        services = self._study_dependencies
        return services.study.status(services.current_profile())

    def study_mode(self, mode: str) -> dict:
        services = self._study_dependencies
        return services.study.set_mode(services.current_profile(), str(mode))

    def study_add_path(self, path: str) -> dict:
        services = self._study_dependencies
        return services.study.add_async(services.current_profile(), path, 'book')

    def study_add_exam_path(self, path: str, year: int, period: str='', session: str='') -> dict:
        services = self._study_dependencies
        return services.study.add_async(services.current_profile(), path, 'exam', int(year), str(period), str(session))

    def study_remove_document(self, doc_id: int) -> bool:
        services = self._study_dependencies
        services.study.remove(services.current_profile(), int(doc_id))
        return True

    def study_clear_documents(self) -> bool:
        services = self._study_dependencies
        services.study.clear(services.current_profile())
        return True

    def study_answer_text(self, question: str, mode: str='') -> str:
        services = self._study_dependencies
        return services.study.ask(services.current_profile(), str(question), str(mode) or None)

    def study_source_info(self, doc_id: int=0, topic: str="") -> dict:
        services = self._study_dependencies
        return services.study.source_info(services.current_profile(), int(doc_id), str(topic))[0]

    def study_answer_with_context(self, question: str, mode: str='', doc_id: int=0, selection=None) -> dict:
        """Cevap + anlatılan konunun adı (yan paneldeki görsel/video araması için)."""
        services = self._study_dependencies
        p = services.current_profile()
        services.llm.set_user_context(p.slug)
        selected_mode = str(mode) or services.study.status(p).get('mode', 'teacher')
        if selected_mode == 'math':
            if not str(question).strip():
                raise ValueError('Çözmek istediğin matematik sorusunu veya konuyu yaz.')
            text = services.study.ask(p, str(question), 'math')
            return {'text': text, 'topic': services.study.last_topic(p),
                    'turns': p.data.get('study', {}).get('math_turns', [])}
        if doc_id or not str(question).strip():
            return services.study.ask_source(p, str(question), int(doc_id), str(mode) or None, selection) if selection else services.study.ask_source(p, str(question), int(doc_id), str(mode) or None)
        text = services.study.ask(p, str(question), str(mode) or None)
        return {'text': text, 'topic': services.study.last_topic(p)}

    def study_lesson(self, topic: str, course: str='', mk: str='', simpler: bool=False) -> dict:
        """Konu anlatımı (uzun, bölümlü). Sesli okuma ayrı: study_speak."""
        services = self._study_dependencies
        return services.study.lesson(services.current_profile(), str(topic), str(course), str(mk), bool(simpler))

    def study_speak(self, text: str) -> bool:
        """Anlatımı Jarvis'in sesiyle okur (Durdur: stop_speaking)."""
        services = self._study_dependencies
        from modules import richtext
        t = richtext.speakable(str(text or ''))
        t = re.sub('\\s*\\n+\\s*', '. ', t)
        t = re.sub('\\.\\s*\\.', '.', t).strip()[:6000]
        if t:
            services.events.put(('say_slow', t))
        return bool(t)
