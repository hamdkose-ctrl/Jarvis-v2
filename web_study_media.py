"""Study media API actions with explicit injected services."""
import re


class WebStudyMedia:

    def study_media(self, topic: str, course: str="") -> dict:
        services = self._study_dependencies
        if services.privacy.blocked('web'):
            return {'topic': topic, 'images': [], 'videos': [], 'search': '', 'blocked': services.privacy.blocked('web')}
        studymedia = services.media
        return studymedia.media(str(topic), str(course)) if course else studymedia.media(str(topic))

    def study_set_youtube_key(self, key: str) -> dict:
        """YouTube Data API anahtarı (ücretsiz): Çalışma ekranında konu videolarını listelemek için."""
        services = self._study_dependencies
        key = str(key or '').strip()
        if key and (not re.fullmatch('AIza[0-9A-Za-z_\\-]{30,}', key)):
            raise ValueError("Bu bir YouTube (Google) API anahtarına benzemiyor; 'AIza' ile başlamalı.")
        studymedia = services.media
        blocked = services.privacy.blocked('web')
        test = ({'ok': None, 'msg': 'İnternet erişimi kapalı; anahtar henüz denenmedi.'}
                if key and blocked else studymedia.check_key(key) if key else {'ok': None, 'msg': ''})
        if key and test.get('ok') is False and ('Günlük' not in str(test.get('msg'))):
            raise ValueError('YouTube anahtarı denendi ama çalışmadı: ' + str(test.get('msg')) + '. Anahtar kaydedilmedi.')
        services.config.set_youtube_key(key)
        studymedia.reset_cache()
        services.privacy.audit('youtube anahtarı', 'kaydedildi' if key else 'silindi')
        return {'ok': True, 'set': bool(key), 'test': test}
