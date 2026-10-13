"""Real desktop Bridge integration, without paid calls or hardware."""
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import headless_smoke
import main,web
from modules import paid_providers,personalization,llm
other=personalization.Profile('PaidOther')
with tempfile.TemporaryDirectory() as tmp,patch.object(paid_providers,'DATA_DIR',Path(tmp)),patch.object(paid_providers.requests,'request') as net:
    token=web._bridge_profile.set(other)
    try:
        before=llm.provider()
        result=web.bridge.paid_provider_save('openai','fake-user-key','account-model')
        assert result['ok']
        assert llm.provider()==before
        assert paid_providers.key(other.slug,'openai')=='fake-user-key'
        assert not paid_providers.key(main.profile.slug,'openai')
        assert not paid_providers.settings(other.slug,'openai')['model']
        assert 'fake-user-key' not in str(result)
        assert paid_providers.settings(other.slug,'openai')['candidate_model']=='account-model'
        net.assert_not_called()
        # Selection must use the captured Bridge owner, not stale LLM context.
        llm.set_user_context(main.profile.slug)
        with patch.object(llm,'status',return_value={}):web.bridge.llm_set('openai')
        assert paid_providers.settings(other.slug,'openai')['model']=='account-model'
        assert llm.current_user()==other.slug
        web.bridge.paid_provider_delete('openai')
        assert not paid_providers.key(other.slug,'openai')
    finally:
        web._bridge_profile.reset(token)
        llm.set_user_context(main.profile.slug)
print('Ücretli sağlayıcı gerçek Bridge: kayıt çağrı/aktivasyon yapmıyor; kullanıcı bağlamı, aday model, onaylı seçim ve anahtar silme doğru.')
