"""Study exams API actions with explicit injected services."""
import re


class WebStudyExams:

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
        return studyexam.set_courses(services.current_profile(), [str(k) for k in keys or []])

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
        return studyexam.quiz_answer(services.current_profile(), str(qid), str(choice), str(attempt_id))

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
        return studyexam.mock_answer(services.current_profile(), str(qid), str(choice), str(session_id))

    def study_plan_set(self, cfg: dict) -> dict:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.set_plan_cfg(services.current_profile(), dict(cfg or {}))

    def study_plan_reminders(self) -> int:
        services = self._study_dependencies
        studyexam = services.exams
        return studyexam.set_reminders(services.current_profile())
