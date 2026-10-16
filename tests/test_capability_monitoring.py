"""Real user journals/files with public HTTP and model boundaries substituted."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from modules import public_sources,source_watch,capability_hub,domain_tools,goal_extensions
from modules import llm,service_store,goal_executor,goal_tools,nxapi,task_agents,task_results


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for obj,name,value in [(service_store,'ROOT',self.root/'services'),(goal_executor,'STORE',self.root/'goals'),(nxapi,'FILES_DIR',self.root/'files')]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        p=patch('modules.privacy.blocked',return_value=None);p.start();self.addCleanup(p.stop)
        self.runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice',data={}),emit=Mock())
        self.index='https://example.org/rss.xml'
        self.articles={'https://example.org/old':'<html><body>Eski eğitim duyurusu.</body></html>'}
        self.items=[('old','Eski eğitim duyurusu','2026-10-14')]
        self.calls=[]

    def fetch(self,url):
        self.calls.append(url)
        if url==self.index:
            body='<rss><channel>'+''.join('<item><title>'+title+'</title><link>https://example.org/'+slug+'</link><pubDate>'+day+'</pubDate></item>' for slug,title,day in self.items)+'</channel></rss>'
            return {'url':url,'body':body.encode(),'content_type':'text/xml'}
        return {'url':url,'body':self.articles[url].encode(),'content_type':'text/html'}

    def add(self,terms=None):return source_watch.add('alice',self.index,terms or ['eğitim'])
    def poll(self,ident,notify=None):return source_watch.poll('alice',notify,fetcher=self.fetch,rule_id=ident,force=True)
    def identity(self,request=''):return {'owner':'alice','job_id':'goal','task_id':'s1','request':request}


class PublicReadTests(unittest.TestCase):
    def test_private_credentials_non_https_and_key_urls_are_rejected(self):
        for url in ['http://example.org','https://localhost/','https://192.168.1.2/','https://127.0.0.1/','https://[::1]/',
                    'https://user:pass@example.org/','https://example.org:444/','https://example.org/?api_key=secret']:
            with self.subTest(url=url),self.assertRaises(ValueError):public_sources.address(url)
        with patch.object(public_sources.socket,'getaddrinfo',return_value=[(2,1,6,'',('10.0.0.2',443))]):
            with self.assertRaises(ValueError):public_sources.address('https://example.org',resolve=True)

    def test_html_atom_and_rss_parse_deduplicate_and_reject_entities(self):
        html=b'<html><body><a href="/a">Resmi duyuru</a><a href="/a">Resmi duyuru</a><a href="https://foreign.org/a">Baska kaynak</a></body></html>'
        rows=public_sources.entries({'url':'https://example.org/','body':html})
        self.assertEqual([r['url'] for r in rows],['https://example.org/a'])
        atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>School update</title><link href="/a"/><updated>2026-10-15</updated></entry></feed>'
        self.assertEqual(public_sources.entries({'url':'https://example.org/','body':atom})[0]['published'],'2026-10-15')
        with self.assertRaises(ValueError):public_sources.entries({'url':'https://example.org/','body':b'<!DOCTYPE rss [<!ENTITY a "unsafe">]><rss/>'})

    def test_fetch_limits_response_and_rechecks_redirects(self):
        import urllib3
        response=Mock(status=200,headers={'Content-Length':'1000001'})
        pool=Mock();pool.urlopen.return_value=response
        records=[(2,1,6,'',('93.184.216.34',443))]
        with patch.object(public_sources.socket,'getaddrinfo',return_value=records),patch.object(urllib3,'HTTPSConnectionPool',return_value=pool) as transport,patch('modules.privacy.blocked',return_value=None):
            with self.assertRaises(ValueError):public_sources.fetch('https://example.org/')
        self.assertEqual(transport.call_args.args[0],'93.184.216.34')
        self.assertEqual(transport.call_args.kwargs['assert_hostname'],'example.org')
        self.assertEqual(transport.call_args.kwargs['server_hostname'],'example.org')
        self.assertFalse(pool.urlopen.call_args.kwargs['redirect'])
        response.close.assert_called_once();pool.close.assert_called_once()



class HeadlineDiscoveryTests(unittest.TestCase):
    def setUp(self):
        token=llm._key_context.set("alice")
        self.addCleanup(llm._key_context.reset,token)

    def test_query_ranks_real_links_before_truncating_without_inventing_dates(self):
        html=('<html><body>'+''.join('<a href="/other'+str(i)+'">Diğer etkinlik duyurusu</a>' for i in range(25))+'<a href="/ai">Yapay zeka araştırma duyurusu</a></body></html>').encode()
        response={'url':'https://example.org/news','body':html}
        result=domain_tools.headlines('alice',response['url'],query='yapay zeka',fetcher=lambda _:response)
        self.assertEqual(result['items'][0]['url'],'https://example.org/ai')
        self.assertEqual(result['items'][0]['published'],'')
        self.assertEqual(len(result['items']),20)
        self.assertEqual(goal_extensions.validate('data',{'operation':'headlines','url':response['url'],'query':'yapay zeka'})['query'],'yapay zeka')

    def test_invalid_query_does_not_fetch(self):
        fetch=Mock()
        with self.assertRaises(ValueError):domain_tools.headlines('alice','https://example.org',query='x'*301,fetcher=fetch)
        fetch.assert_not_called()

    def test_image_or_accessible_label_links_are_real_discovery_candidates(self):
        response={'url':'https://example.org/haberler','body':b'<a href="/a"><img alt="Research project announced"></a><a href="/b" aria-label="Science announcement"></a>'}
        self.assertEqual([x['url'] for x in public_sources.entries(response)],['https://example.org/a','https://example.org/b'])

    def test_advertised_same_host_feed_is_used_when_index_has_no_entries(self):
        index='https://example.org/haberler';feed='https://example.org/rss.xml'
        html=b'<link type="application/rss+xml" href="https://foreign.org/rss"><link type="application/rss+xml" href="/rss.xml">'
        rss=b'<rss><channel><item><title>Research project announced</title><link>https://example.org/article</link></item></channel></rss>'
        fetch=Mock(side_effect=[{'url':index,'body':html},{'url':feed,'body':rss}])
        result=domain_tools.headlines('alice',index,fetcher=fetch)
        self.assertEqual([call.args[0] for call in fetch.call_args_list],[index,feed])
        self.assertEqual(result['source'],feed);self.assertEqual(result['discovered_from'],index)
        self.assertEqual(result['items'][0]['url'],'https://example.org/article')
        self.assertEqual(result['sha256'],hashlib.sha256(rss).hexdigest())

    def test_feed_fallback_is_bounded_and_permission_failure_is_not_swallowed(self):
        index='https://example.org/haberler'
        html=(''.join('<link type="application/rss+xml" href="/rss'+str(i)+'">' for i in range(5))).encode()
        fetch=Mock(side_effect=[{'url':index,'body':html},OSError('offline'),OSError('offline')])
        with self.assertRaises(ValueError):domain_tools.headlines('alice',index,fetcher=fetch)
        self.assertEqual(fetch.call_count,3)
        fetch=Mock(side_effect=[{'url':index,'body':html},PermissionError('Web disabled')])
        with self.assertRaises(PermissionError):domain_tools.headlines('alice',index,fetcher=fetch)
        self.assertEqual(fetch.call_count,2)


class WatchTests(SourceFixture):
    def test_initial_scan_is_silent_then_new_matching_article_notifies_once(self):
        ident=self.add(['tatil']);notify=Mock()
        self.assertEqual(self.poll(ident,notify),[]);notify.assert_not_called()
        self.items.insert(0,('new','Basın açıklaması','2026-10-15'))
        self.articles['https://example.org/new']='<html><body>15 Ekim tarihinde tüm okullar tatil değildir. Yalnız belirli ilçeler için ayrı karar vardır.</body></html>'
        self.assertEqual(len(self.poll(ident,notify)),1)
        self.poll(ident,notify);self.assertEqual(notify.call_count,1)
        event=source_watch.events('alice')[0]
        self.assertIn('tatil değildir',event['quote']);self.assertEqual(event['published'],'2026-10-15')
        self.assertEqual(event['interpretation'],'source_quote_only');self.assertTrue(event['notified'])

    def test_same_url_correction_is_detected_but_layout_noise_is_not(self):
        ident=self.add();self.poll(ident)
        self.articles['https://example.org/old']='<html><body>Eğitim yalnız iki ilçede durduruldu. Diğer ilçeler kapsam dışıdır.</body></html>'
        self.assertEqual(len(self.poll(ident)),1)
        self.articles['https://example.org/old']='<html><nav>changed menu</nav><body>Eğitim yalnız iki ilçede durduruldu. Diğer ilçeler kapsam dışıdır.</body></html>'
        self.assertEqual(self.poll(ident),[])
        self.assertEqual(len(source_watch.events('alice')),1)

    def test_lost_notification_is_retried_from_durable_record(self):
        ident=self.add();self.poll(ident)
        self.articles['https://example.org/old']='<html><body>Eğitim kararı düzeltildi.</body></html>'
        with self.assertRaises(RuntimeError):self.poll(ident,Mock(side_effect=RuntimeError('emit lost')))
        self.assertFalse(source_watch.events('alice')[0]['notified'])
        notify=Mock();self.poll(ident,notify);notify.assert_called_once()
        self.assertTrue(source_watch.events('alice')[0]['notified'])

    def test_pause_cancel_owner_and_fetch_failure_do_not_claim_success(self):
        ident=self.add();source_watch.pause('alice',ident)
        self.poll(ident);self.assertEqual(self.calls,[])
        with self.assertRaises(PermissionError):source_watch.rows('bob')
        source_watch.pause('alice',ident,False)
        source_watch.poll('alice',rule_id=ident,force=True,fetcher=Mock(side_effect=RuntimeError('offline')))
        self.assertEqual(source_watch.rows('alice')[0]['error'],'RuntimeError')
        source_watch.remove('alice',ident);self.assertEqual(source_watch.rows('alice'),[])

    def test_cancel_during_source_fetch_cannot_create_event(self):
        ident=self.add()
        def fetch(url):
            source_watch.remove('alice',ident)
            return self.fetch(url)
        self.assertIsNone(source_watch.poll('alice',rule_id=ident,force=True,fetcher=fetch))
        self.assertEqual(source_watch.events('alice'),[])

    def test_monitor_registration_requires_explicit_source_and_topic_intent(self):
        data={'operation':'add','url':self.index,'terms':['eğitim']}
        with self.assertRaises(goal_tools.NotStarted):goal_extensions.execute(self.runtime,'monitor',data,self.identity('Bir rapor yaz'))
        with self.assertRaises(goal_tools.NotStarted):goal_extensions.execute(self.runtime,'monitor',data,self.identity('Eğitim duyurularını izle'))
        out=goal_extensions.execute(self.runtime,'monitor',data,self.identity(self.index+' adresindeki eğitim duyurularını takip et'))
        self.assertEqual(out['state'],'done');self.assertEqual(len(source_watch.rows('alice')),1)
        goal_extensions.execute(self.runtime,'monitor',data,self.identity(self.index+' adresini takip et'))
        self.assertEqual(len(source_watch.rows('alice')),1)

    def test_known_official_source_can_be_selected_for_matching_explicit_topic(self):
        data={'operation':'add','url':'https://istanbul.meb.gov.tr/','terms':['tatil']}
        out=goal_extensions.execute(self.runtime,'monitor',data,self.identity('İstanbul okul duyurularını takip et'))
        self.assertEqual(out['state'],'done')
        self.assertEqual(source_watch.rows('alice')[0]['url'],data['url'])

    def test_monitor_lost_registration_response_is_reconciled_without_second_rule(self):
        data={'operation':'add','url':self.index,'terms':['eğitim']}
        check=goal_extensions.checkpoint(self.runtime,'monitor',data)
        self.add();result=goal_extensions.reconcile(self.runtime,'monitor',data,self.identity(),check)
        self.assertEqual(result['state'],'done');self.assertTrue(result['reconciled'])
        self.assertEqual(len(source_watch.rows('alice')),1)

    def test_manual_check_in_private_mode_or_paused_is_not_success(self):
        ident=self.add();data={'operation':'check','id':ident}
        with patch('modules.privacy.blocked',return_value='blocked'),self.assertRaises(goal_tools.NotStarted):
            goal_extensions.execute(self.runtime,'monitor',data,self.identity())
        source_watch.pause('alice',ident)
        with self.assertRaises(goal_tools.NotStarted):goal_extensions.execute(self.runtime,'monitor',data,self.identity())


class CapabilityTests(SourceFixture):
    def catalog(self,url):
        body='### Data APIs\n| [Weather Example](https://example.org/docs) | Weather data | No | Yes |\n### MCP Servers\n| [Weather MCP](https://example.org/mcp) | Weather tools | No | HTTP |'
        return {'url':url,'body':body.encode(),'content_type':'text/plain'}

    def candidate(self):return capability_hub.discover('alice','Weather',fetcher=self.catalog)['candidates'][0]['id']

    def test_discovery_is_cached_owned_and_not_claimed_connected_or_free(self):
        fetch=Mock(side_effect=self.catalog)
        result=capability_hub.discover('alice','Weather',fetcher=fetch)
        self.assertEqual(fetch.call_count,2);self.assertEqual(len(result['candidates']),2)
        self.assertTrue(any(r['kind']=='mcp_reference' for r in result['candidates']))
        self.assertTrue(all(not r['pricing_verified'] for r in result['candidates']))
        capability_hub.discover('alice','Weather',fetcher=fetch);self.assertEqual(fetch.call_count,2)
        self.assertTrue(all(r['binding'] is None for r in capability_hub.rows('alice')))
        with self.assertRaises(PermissionError):capability_hub.rows('bob')

    def test_assessment_reads_evidence_without_installing_mcp_code(self):
        ident=self.candidate();document=b'<html><body>Example docs. Authorization and pricing require review.</body></html>'
        out=capability_hub.assess('alice',ident,fetcher=lambda url:{'url':url,'body':document})
        self.assertEqual(out['document_sha256'],hashlib.sha256(document).hexdigest())
        self.assertFalse(out['code_installed']);self.assertFalse(out['operation_tested'])

    def test_binding_is_exact_confirmed_public_get_with_typed_arguments(self):
        ident=self.candidate();endpoint='https://example.org/api'
        preview=capability_hub.public_binding('alice',ident,endpoint,{'city':'string'})
        self.assertEqual(preview['state'],'approval');self.assertIsNone(capability_hub.rows('alice')[0]['binding'])
        capability_hub.public_binding('alice',ident,endpoint,{'city':'string'},confirmed=True)
        fetch=Mock(return_value={'url':endpoint,'body':b'{"temperature":20}'})
        out=capability_hub.read('alice',ident,{'city':'Istanbul'},fetcher=fetch)
        self.assertEqual(out['data']['temperature'],20);self.assertIn('city=Istanbul',fetch.call_args.args[0])
        with self.assertRaises(ValueError):capability_hub.read('alice',ident,{'api_key':'anything'},fetcher=fetch)
        capability_hub.unbind('alice',ident)
        with self.assertRaises(ValueError):capability_hub.read('alice',ident,{},fetcher=fetch)

    def test_binding_never_accepts_auth_or_write_operation_fields(self):
        ident=self.candidate()
        for endpoint,params in [('http://example.org/api',{}),('https://localhost/api',{}),('https://example.org/delete',{}),
                                ('https://example.org/api',{'token':'string'}),('https://example.org/api',{'action':'string'})]:
            with self.subTest(endpoint=endpoint,params=params),self.assertRaises(ValueError):
                capability_hub.public_binding('alice',ident,endpoint,params,confirmed=True)

    def test_api_secrets_are_removed_from_structured_and_human_output(self):
        ident=self.candidate();capability_hub.public_binding('alice',ident,'https://example.org/api',{},confirmed=True)
        with patch.object(public_sources,'fetch',return_value={'url':'https://example.org/api','body':b'{"access_token":"unusual-secret","value":2}'}):
            output=goal_extensions.execute(self.runtime,'capability',{'operation':'read','id':ident,'parameters':{}},self.identity())
        self.assertNotIn('unusual-secret',json.dumps(output))


class DomainTests(SourceFixture):
    def csv(self,text):
        path=self.root/'data.csv';path.write_text(text,encoding='utf-8');return path

    def test_finance_and_store_use_actual_rows_and_preserve_source(self):
        path=self.csv('type;amount\ngelir;125,50\ngider;25,25\n');original=path.read_bytes()
        with patch.object(nxapi,'allowed',return_value=path):
            out=domain_tools.csv_analysis('alice','finance',str(path),{'amount':'amount','kind':'type'},',')
        self.assertEqual(out['result']['net'],'100.25');self.assertEqual(path.read_bytes(),original)
        path=self.csv('sku,qty,min,price\nA,2,5,10\nB,8,4,3\n')
        with patch.object(nxapi,'allowed',return_value=path):
            out=domain_tools.csv_analysis('alice','store',str(path),{'sku':'sku','quantity':'qty','minimum':'min','price':'price'})
        self.assertEqual(out['result']['inventory_value'],'44')
        self.assertEqual(out['result']['below_minimum'][0]['difference'],'3')

    def test_bad_rows_are_not_silently_dropped_or_number_formats_guessed(self):
        path=self.csv('type,amount\nunknown,25\n')
        with patch.object(nxapi,'allowed',return_value=path),self.assertRaises(ValueError):
            domain_tools.csv_analysis('alice','finance',str(path),{'amount':'amount','kind':'type'})
        for text in ('NaN','Infinity','1,25'):
            with self.assertRaises(ValueError):domain_tools._amount(text)

    def test_dated_exchange_result_checks_currency_and_rate_not_just_http_success(self):
        response={'url':'https://api.frankfurter.dev/v2/rate/usd/try','body':json.dumps({'base':'USD','quote':'TRY','rate':40.2,'date':'2026-10-14'}).encode()}
        out=domain_tools.exchange('alice','USD','TRY','2026-10-15',fetcher=lambda url:response)
        self.assertEqual(out['data']['date'],'2026-10-14');self.assertIn('Günlük',out['scope'])
        with self.assertRaises(ValueError):domain_tools.exchange('alice','EUR','TRY',fetcher=lambda url:response)

    def test_csv_source_receipt_invalidates_when_file_changes(self):
        path=self.csv('type,amount\ngelir,100\n')
        data={'operation':'finance_csv','path':str(path),'columns':{'amount':'amount','kind':'type'}}
        with patch.object(nxapi,'allowed',return_value=path):output=goal_extensions.execute(self.runtime,'data',data,self.identity())
        self.assertTrue(goal_tools.verify(output,'alice'))
        path.write_text('changed')
        with self.assertRaises(ValueError):goal_tools.verify(output,'alice')

    def test_common_goal_can_recover_then_deliver_real_domain_report(self):
        path=self.csv('type,amount\ngelir,100\ngider,25\n')
        responses=[{'action':'plan','goals':['Finans dosyasını analiz et ve rapor dosyası üret']},
            {'action':'tool','goal':0,'tool':'data','input':{'operation':'finance_csv','path':str(path),'columns':{'amount':'amount','kind':'type'}}},
            {'action':'tool','goal':0,'tool':'writer','input':{'instruction':'Gerçek analiz verilerinden rapor yaz','filename':'finans.md'},'depends':['s1']},
            'Gelir 100, gider 25, net 75. Kaynak verilen CSV dosyasıdır.',
            {'action':'complete','goal':0,'evidence':['s1','s2']},{'action':'finish'}]
        from modules import team_center
        with patch.object(llm,'ask',side_effect=[json.dumps(r) if isinstance(r,dict) else r for r in responses]),patch.object(nxapi,'allowed',return_value=path),patch.object(team_center,'ROOT',self.root/'teams'):
            result=goal_executor.run(self.runtime,'Bu finans CSV dosyasını analiz et ve rapor dosyası oluştur')
        job=goal_executor.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertIn('net 75',Path(job['outputs']['s2']['file']).read_text())
        self.assertEqual(job['steps'][0]['specialist']['id'],'finance')
