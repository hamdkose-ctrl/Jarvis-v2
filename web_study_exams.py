"""Study exams API actions with explicit injected services."""
import re


class WebStudyExams:

    @staticmethod
    def _study_state(profile) -> dict:
        data = getattr(profile, 'data', None)
        if not isinstance(data, dict):
            return {}
        state = data.get('study')
        return state if isinstance(state, dict) else {}

    @staticmethod
    def _course_keys(keys) -> list[str]:
        """Tek seçim/string dâhil farklı istemci biçimlerini güvenli listeye çevirir."""
        if isinstance(keys, str):
            raw = [keys]
        elif isinstance(keys, (list, tuple, set)):
            raw = list(keys)
        else:
            raw = []
        out = []
        for key in raw:
            value = str(key or '').strip()
            if value and value not in out:
                out.append(value)
        return out

    def study_exam_analysis(self, force: bool=True) -> dict:
        """En yeni üç yılın çıkmış sorularından konu/soru tipi istatistiği çıkarır."""
        services = self._study_dependencies
        return services.study.analyze_recent_exams(services.current_profile(), bool(force))

    def study_courses(self) -> list:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.courses(services.current_profile())

    def study_set_courses(self, keys: list) -> list:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.set_courses(services.current_profile(), self._course_keys(keys))

    def study_overview(self) -> dict:
        """Derslerim + konu başarıları + öncelikli konular + haftalık program (hepsi yapay zekâsız, anında)."""
        services = self._study_dependencies
        studyexam = services.exams
        p = services.current_profile()
        st = studyexam.stats(p)
        ss = services.study.status(p)
        return {'courses': studyexam.courses(p), 'selected': studyexam.selected(p), 'stats': st, 'focus': studyexam.focus(p, 3), 'focus_all': studyexam.focus(p, 40), 'plan': studyexam.plan(p), 'today': studyexam.today(p), 'wrong': studyexam.wrong_summary(p), 'mock': studyexam.mock_status(p), 'coverage': {'years': ss.get('recent_exam_years', []), 'year_count': len(ss.get('recent_exam_years', [])), 'exam_files': len(ss.get('exams', []))}}

    def study_quiz_next(self, mk: str='', topic: str='') -> dict | None:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.quiz_next(services.current_profile(), str(mk) or None, str(topic) or None)

    def study_quiz_answer(self, qid: str, choice: str, attempt_id: str='') -> dict:
        services = self._study_dependencies
        studyexam = services.exams
        p = services.current_profile()
        qid = str(qid)
        attempt_id = str(attempt_id)
        active = self._study_state(p).get('quiz_attempt') or {}
        if isinstance(active, dict) and active.get('qid'):
            if str(active.get('qid')) != qid:
                raise ValueError('Bu soru denemesi artık aktif değil; yeni soruyu cevapla.')
            if not attempt_id and active.get('id'):
                attempt_id = str(active['id'])
        return studyexam.quiz_answer(p, qid, str(choice), attempt_id)

    def study_explain(self, qid: str, choice: str='') -> str:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.explain(services.current_profile(), str(qid), str(choice))

    def study_wrong_next(self) -> dict | None:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.wrong_next(services.current_profile())

    def study_mock_start(self, count: int=10) -> dict:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.mock_start(services.current_profile(), int(count))

    def study_mock_status(self) -> dict:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.mock_status(services.current_profile())

    def study_mock_answer(self, qid: str, choice: str, session_id: str='') -> dict:
        services = self._study_dependencies
        studyexam = services.exams
        p = services.current_profile()
        session_id = str(session_id)
        active = self._study_state(p).get('mock_session') or {}
        if not session_id and isinstance(active, dict) and active.get('id'):
            session_id = str(active['id'])
        return studyexam.mock_answer(p, str(qid), str(choice), session_id)

    def study_plan_set(self, cfg: dict) -> dict:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.set_plan_cfg(services.current_profile(), dict(cfg or {}))

    def study_plan_reminders(self) -> int:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.set_reminders(services.current_profile())
