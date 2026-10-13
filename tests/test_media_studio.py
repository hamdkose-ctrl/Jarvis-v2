import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from modules import media_tools,media_studio,local_narration,task_results,nxapi,llm,publish_services,outbox,service_store,task_agents


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        for mod,name,path in ((nxapi,'FILES_DIR',self.root),(service_store,'ROOT',self.root/'service'),(task_agents,'STORE',self.root/'tasks')):
            p=patch.object(mod,name,path);p.start();self.addCleanup(p.stop)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg unavailable')
    def test_real_portrait_caption_montage_and_audio_stream(self):
        audio=self.root/'audio.wav'
        with wave.open(str(audio),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*32000)
        data=media_tools.prepare({'scenes':[{'caption':'Birinci sahne','duration':1},{'caption':'İkinci sahne','duration':1}],
                                  'layout':'portrait','audio':str(audio)})
        out=task_results.seal('media',media_tools.run('alice',data))
        self.assertTrue(task_results.verify(out));self.assertEqual(out['media']['height'],1280);self.assertEqual(out['media']['width'],720)
        self.assertTrue(out['media']['has_audio']);self.assertEqual(out['studio']['scenes'],2)
        self.assertFalse(list(Path(out['file']).parent.glob('studio-*')))

    def test_invalid_storyboard_never_calls_renderer(self):
        for data in ({'scenes':[]},{'scenes':[{'duration':1}]},{'scenes':[{'caption':'x','duration':True}]},
                     {'scenes':[{'caption':'x','duration':61}]},{'scenes':[{'caption':'x'*401}]},
                     {'scenes':[{'caption':'x'}],'layout':'unknown'}):
            with self.assertRaises(ValueError):media_tools.validate(data)

    def test_local_narration_has_no_cloud_fallback(self):
        with patch.object(publish_services,'configuration',return_value={}),patch.object(local_narration.shutil,'which',return_value=None),patch.object(local_narration.sys,'platform','linux'):
            with self.assertRaises(local_narration.Unavailable):local_narration.render('alice','Merhaba',self.root/'out.wav')

    def test_verified_writer_body_can_feed_exact_send_preview(self):
        from modules import browser_agent
        payload={'service':'gmail','destination':'friend@example.com','subject':'Reply','text_from_task':'draft'}
        tasks=[{'id':'draft','agent':'writer','input':{'instruction':'Cevap yaz'}},{'id':'send','agent':'publish','depends':['draft'],'input':payload}]
        with patch.object(browser_agent,'STORE',self.root/'browser'),patch.object(llm,'ask',return_value='Actual reply body'),patch.object(publish_services,'send') as send:
            job=task_agents.execute('alice',tasks);send.assert_not_called()
        self.assertEqual(job['state'],'approval')
        self.assertEqual(outbox.get('alice',job['outputs']['send']['id'])['payload']['text'],'Actual reply body')


if __name__=='__main__':unittest.main()
