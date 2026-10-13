"""Study bridge composition; legacy endpoint aliases remain compatible."""
from web_study_sources import WebStudySources
from web_study_exams import WebStudyExams
from web_study_media import WebStudyMedia
from modules.study_services import StudyServices


class WebStudy(WebStudySources, WebStudyExams, WebStudyMedia):
    def __init__(self, services: StudyServices):
        self._study_dependencies = services

    # Compatibility for older cached UI / integrations.
    def study_remove(self, did):
        return self.study_remove_document(did)

    def study_clear(self):
        return self.study_clear_documents()

    def study_ask(self, *args, **kwargs):
        return self.study_answer_text(*args, **kwargs)

    def study_ask2(self, *args, **kwargs):
        return self.study_answer_with_context(*args, **kwargs)

    def study_youtube_key(self, *args, **kwargs):
        return self.study_set_youtube_key(*args, **kwargs)
