"""Real desktop Bridge integration for generic custom roles; no provider calls."""
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import headless_smoke
import main,web,config
from modules import router_connections,user_models,provider_protocols,personalization,llm,smart_router,image_gen
other=personalization.Profile('CustomOther')
with tempfile.TemporaryDirectory() as tmp,patch.object(config,'DATA_DIR',Path(tmp)),patch.object(router_connections,'DATA_DIR',Path(tmp)),patch.object(user_models,'DATA_DIR',Path(tmp)),patch.object(smart_router,'_STORE',Path(tmp)/'router'),patch.object(provider_protocols.requests,'request') as net:
    token=web._bridge_profile.set(other)
    try:
        before=llm.provider()
        record=dict(name='Custom',protocol='responses',base_url='https://api.example.org/v1',model='account-model',
            role='conversation',billing='paid',paid_enabled=True,enabled=True,data_scopes=['conversation'],daily_requests=10,max_output_tokens=4096)
        llm.set_user_context(main.profile.slug)
        result=web.bridge.router_connection_save(record,'fake-user-key',other.slug)
        assert result['ok'] and llm.provider()==before
        identity=result['connection']['id']
        assert router_connections.resolve(other.slug,identity)[1]=='fake-user-key'
        assert router_connections.snapshot(main.profile.slug)==[]
        assert 'fake-user-key' not in str(result)
        assert smart_router.plan(smart_router.ModelRequest(owner=other.slug)).candidates[0].connection_id==identity
        try:web.bridge.router_connection_delete(identity,main.profile.slug)
        except PermissionError:pass
        else:raise AssertionError('stale Bridge owner accepted')
        web.bridge.router_connection_delete(identity,other.slug)
        assert router_connections.snapshot(other.slug)==[]
        cf=web.bridge.router_cloudflare_save('a'*32,'synthetic-cf-key',False,other.slug)
        assert cf['ok'] and image_gen.user_cloudflare_token(other.slug)=='synthetic-cf-key'
        assert not image_gen.user_cloudflare_token(main.profile.slug)
        web.bridge.router_cloudflare_save('','',True,other.slug)
        assert not image_gen.user_cloudflare_token(other.slug)
        net.assert_not_called()
    finally:
        web._bridge_profile.reset(token);llm.set_user_context(main.profile.slug)
print('Özel API gerçek Bridge: kayıt model çağırmıyor; kullanıcı/rol/secret sınırları ve eski kullanıcı isteğinin reddi doğru.')
