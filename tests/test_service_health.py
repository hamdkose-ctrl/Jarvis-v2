import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import llm, service_health, publish_services, task_agents


class ServiceHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for p in (patch.object(service_health,'DATA_DIR',self.root),patch.object(publish_services,'DATA_DIR',self.root),
                  patch.object(service_health.shutil,'which',return_value=None),patch.object(service_health.sys,'platform','linux')):
            p.start();self.addCleanup(p.stop)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)

    def test_missing_configuration_does_not_write_or_contact_services(self):
        with patch.object(publish_services,'_http',side_effect=AssertionError('network')):
            result=service_health.report('alice')
        self.assertIn('ffmpeg: bulunamadı',result);self.assertEqual(list(self.root.iterdir()),[])

    def test_owner_isolation_and_no_secret_disclosure(self):
        for owner in ('alice','bob'):
            folder=self.root/'google_users'/owner;folder.mkdir(parents=True)
            (folder/'google_token.json').write_text('PRIVATE_TOKEN')
        result=service_health.report('alice');self.assertNotIn('PRIVATE_TOKEN',result)
        (self.root/'google_users'/'alice'/'google_token.json').unlink()
        self.assertIn('Gmail okuma: kullanıcı OAuth dosyası yok',service_health.report('alice'))
        with self.assertRaises(PermissionError):service_health.report('bob')

    def test_invalid_config_and_symlink_do_not_report_ready(self):
        folder=self.root/'connector_users'/'alice';folder.mkdir(parents=True)
        (folder/'telegram.json').write_text('{SECRET')
        other=self.root/'secret.json';other.write_text(json.dumps({'access_token':'SECRET'}))
        (folder/'instagram.json').symlink_to(other)
        result=service_health.report('alice')
        self.assertIn('Telegram: yapılandırma okunamadı',result)
        self.assertIn('Instagram: yapılandırma okunamadı',result);self.assertNotIn('SECRET',result)

    def test_command_restores_context_and_reports_explicit_flags(self):
        folder=self.root/'connector_users'/'alice';folder.mkdir(parents=True)
        (folder/'whatsapp.json').write_text(json.dumps({'access_token':'SECRET','api_version':'v23.0','phone_number_id':'123',
            'allow_service_costs':True,'webhook_enabled':True,'app_secret':'a'*16,'verify_token':'b'*16}))
        result=task_agents.handle('alice','hesap durumu')
        self.assertEqual(llm._key_context.get(),'alice')
        self.assertIn('WhatsApp maliyet yetkisi: açık',result)
        self.assertIn('çalışan dinleyici doğrulanmadı',result);self.assertNotIn('SECRET',result)
