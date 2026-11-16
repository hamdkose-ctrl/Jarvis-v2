"""Phase 4A: only media and file may join the canonical Scheduler.

Use real GoalState, Scheduler admission, ResourceLease, native domain receipts,
and Core WorkerResult CAS; mock only FFmpeg/FFprobe physical execution.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_canonical_effectful_scheduler import CanonicalEffectfulSchedulerTests as _Harness
from modules import task_agents, worker_result_hook, worker_result_commit, requests_state, task_queue
from modules import (
    canonical_goal_flow, canonical_scheduler_dispatch, effect_recovery_runtime,
    file_worker, goal_executor, media_tools, model_wait, task_results,
    task_workers, task_worker_adapter,
)


class Phase4AMediaFileTests(unittest.TestCase):
    setUp = _Harness.setUp
    create = _Harness.create
    create_plan = _Harness.create_plan
    snapshots = _Harness.snapshots
    offer = _Harness.offer

    def run_offer(self, job_id, *, owner='alice'):
        return canonical_scheduler_dispatch.execute_offer(
            SimpleNamespace(slug=owner), self.offer(job_id),
        )

    def test_only_media_and_file_enter_phase4a(self):
        with self.assertRaises(ValueError):
            canonical_goal_flow._canonical_plan([
                {'id':'pay','agent':'finance','depends':[],
                 'input':{'operation':'portfolio_summary','payload':'[]'}},
            ],allow_effects=True)
        with self.assertRaises(ValueError):
            canonical_goal_flow._canonical_plan([
                {'id':'ui','agent':'computer','depends':[],
                 'input':{'app':'calculator','operation':'observe'}},
            ],allow_effects=True)
        with self.assertRaises(ValueError):
            canonical_goal_flow._canonical_plan([
                {'id':'browse','agent':'browser','depends':[],
                 'input':{'url':'https://example.org','instruction':'Read'}},
            ],allow_effects=True)
        with self.assertRaises(ValueError):
            canonical_goal_flow._canonical_plan([
                {'id':'first','agent':'research','depends':[],
                 'input':{'url':'https://example.org'}},
                {'id':'video','agent':'media','depends':['first'],
                 'input':{'scenes':[{'caption':'One','duration':3}]}},
            ],allow_effects=True)

    def test_file_real_readback_worker_result_and_source_mutation(self):
        source=self.root/'report.txt'
        source.write_text('The report must be filed by 2027-01-01.',encoding='utf-8')
        job_id=self.create({'id':'read','agent':'file','depends':[],
            'input':{'path':str(source),'operation':'extract_obligations'}},
            'Read this document for deadlines and obligations.')
        with patch.object(file_worker,'allowed_roots',return_value=[self.root]), \
             patch.object(task_worker_adapter,'worker',wraps=task_worker_adapter.worker) as native:
            self.assertTrue(self.run_offer(job_id))
        native.assert_called_once()
        state,record=self.snapshots(job_id)
        evidence=state['evidence']
        self.assertEqual(len(evidence),1)
        self.assertEqual(evidence[0]['capability_id'],'task.file')
        self.assertEqual(evidence[0]['command_id'],'read:1:p1')
        self.assertEqual(evidence[0]['status'],'succeeded')
        self.assertEqual(record['steps'][0]['attempts'],1)
        with patch.object(file_worker,'allowed_roots',return_value=[self.root]):
            self.assertTrue(task_results.verify(record['outputs']['read'],owner=self.owner))
            source.write_text('Content changed after execution',encoding='utf-8')
            with self.assertRaises(ValueError):
                task_results.verify(record['outputs']['read'],owner=self.owner)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())

    def test_file_requires_real_digest_and_allowed_location(self):
        source=self.root/'read.txt'
        source.write_text('Must review document.',encoding='utf-8')
        invalid={'state':'done','text':'Read','obligations':[],
                 'file_evidence':{'path':str(source),'identity':str(source.resolve()),
                   'digest':'0'*64,'reason_code':'OK','locations':[],'warnings':[]}}
        with patch.object(file_worker,'allowed_roots',return_value=[self.root]):
            with self.assertRaises(ValueError):
                task_results.seal('file',invalid)
        with self.assertRaises(ValueError):
            task_results.seal('file',invalid)

    def test_owner_bound_file_offer_blocks_foreign_worker(self):
        source=self.root/'read.txt'
        source.write_text('Read this document',encoding='utf-8')
        job_id=self.create({'id':'read','agent':'file','depends':[],
            'input':{'path':str(source),'operation':'extract_obligations'}},
            'Read the selected document.')
        with patch.object(task_workers,'run',side_effect=AssertionError('No worker')):
            with self.assertRaises(PermissionError):
                self.run_offer(job_id,owner='bob')
        state,record=self.snapshots(job_id)
        self.assertEqual(state['evidence'],[])
        self.assertEqual(record['steps'][0]['attempts'],0)

    def test_media_first_attempt_has_durable_receipt_and_no_double_render(self):
        image=self.root/'files'/'source.png'
        image.parent.mkdir(parents=True,exist_ok=True)
        image.write_bytes(b'local-source-placeholder')
        video=self.root/'video.mp4'
        video.write_bytes(b'local-ffmpeg-test-fixture')
        metadata={'width':1280,'height':720,'duration':3.0,'has_audio':False}
        job_id=self.create({'id':'video','agent':'media','depends':[],
            'input':{'image':str(image),'image_sha256':task_results.file_digest(image),
                     'duration':3}},'Produce one video from my local image.')
        with patch.object(task_workers,'run',return_value={
                'state':'done','text':'Local video rendered','file':str(video),
                'sha256':task_results.file_digest(video),'media':metadata}) as native, \
             patch.object(media_tools,'probe',return_value=metadata):
            self.assertTrue(self.run_offer(job_id))
            native.assert_called_once()
            state,record=self.snapshots(job_id)
            self.assertEqual(len(state['evidence']),1)
            accepted=state['evidence'][0]
            self.assertEqual(accepted['capability_id'],'task.media')
            self.assertEqual(accepted['status'],'succeeded')
            self.assertEqual(accepted['command_id'],'video:1:p1')
            self.assertEqual(record['steps'][0]['attempts'],1)
            self.assertTrue(task_results.verify(record['outputs']['video'],owner=self.owner))
            self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())
            with self.assertRaises(Exception):
                self.run_offer(job_id)
            native.assert_called_once()

    def test_media_intent_failure_prevents_native_worker_and_retries(self):
        image=self.root/'files'/'source.png'
        image.parent.mkdir(parents=True,exist_ok=True)
        image.write_bytes(b'local-source-placeholder')
        job_id=self.create({'id':'video','agent':'media','depends':[],
            'input':{'image':str(image),'image_sha256':task_results.file_digest(image),
                     'duration':3}},'Create a video from the source file.')
        with patch.object(effect_recovery_runtime,'record_intent',
                          side_effect=ValueError('Intent journal unavailable')), \
             patch.object(task_workers,'run') as native:
            with self.assertRaises(ValueError):
                self.run_offer(job_id)
            native.assert_not_called()
        state,record=self.snapshots(job_id)
        self.assertEqual(state['evidence'],[])
        self.assertEqual(record['steps'][0]['attempts'],1)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())

    def test_media_unproven_receipt_never_commits_and_never_reruns(self):
        image=self.root/'files'/'source.png'
        image.parent.mkdir(parents=True,exist_ok=True)
        image.write_bytes(b'local-source-placeholder')
        video=self.root/'video.mp4'
        video.write_bytes(b'local-ffmpeg-test-fixture')
        metadata={'width':1280,'height':720,'duration':3.0,'has_audio':False}
        job_id=self.create({'id':'video','agent':'media','depends':[],
            'input':{'image':str(image),'image_sha256':task_results.file_digest(image),
                     'duration':3}},'Create a video.')
        with patch.object(task_workers,'run',return_value={
                'state':'done','text':'Local video rendered','file':str(video),
                'sha256':task_results.file_digest(video),'media':metadata}) as native, \
             patch.object(media_tools,'probe',return_value=metadata), \
             patch.object(effect_recovery_runtime,'record_receipt',
                          side_effect=ValueError('No verified local receipt')):
            with self.assertRaises(ValueError):
                self.run_offer(job_id)
            native.assert_called_once()
        state,record=self.snapshots(job_id)
        self.assertFalse(state['evidence'])
        self.assertEqual(record['steps'][0]['attempts'],1)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())

    def test_same_request_rid_never_plans_or_executes_twice(self):
        source=self.root/'doc.txt'
        source.write_text('Review this report by 2027-01-01.',encoding='utf-8')
        rid='phase4a-file-unique-request'
        tasks=[{'id':'read','agent':'file','depends':[],
                'input':{'path':str(source),'operation':'extract_obligations'}}]
        with patch.object(model_wait,'ask',return_value=json.dumps({'tasks':tasks})) as planner:
            first=canonical_goal_flow.try_create(self.owner,rid,'Read the file')
            second=canonical_goal_flow.try_create(self.owner,rid,'Read the file')
        self.assertEqual(first[0],second[0])
        planner.assert_called_once()
        with patch.object(file_worker,'allowed_roots',return_value=[self.root]), \
             patch.object(task_worker_adapter,'worker',wraps=task_worker_adapter.worker) as native:
            self.assertTrue(self.run_offer(first[0]))
            native.assert_called_once()
            self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())



    def _assert_byte_identical_worker_result(self, task, request, *,
                                             render=None, file_root=None):
        """Run the exact same native domain operation once through legacy
        task_agents.worker and once through the real canonical Scheduler.
        Legacy sealed output predates WorkerResult; bind BOTH outputs to the
        canonical execution identity and compare their complete v2 envelopes.
        """
        job_id = self.create(task, request)
        legacy_task = {
            'id': task['id'], 'agent': task['agent'],
            'input': task['input'],
            'execution': {'owner':self.owner, 'job_id':job_id,
                          'task_id':task['id'], 'request':request},
        }
        from contextlib import ExitStack
        with ExitStack() as stack:
            if file_root:
                stack.enter_context(patch.object(file_worker, 'allowed_roots',
                                                 return_value=[self.root]))
            if render is not None:
                stack.enter_context(patch.object(task_workers, 'run', return_value=render))
                stack.enter_context(patch.object(media_tools, 'probe',
                                                 return_value=render['media']))
            legacy = task_agents.worker(self.owner, legacy_task, {})
            observed = []
            native_wrapper = worker_result_hook.wrap_output
            def capture(output, identity):
                result = native_wrapper(output, identity)
                observed.append(result)
                return result
            with patch.object(worker_result_hook, 'wrap_output',
                              side_effect=capture) as wrapped:
                self.assertTrue(self.run_offer(job_id))
            self.assertEqual(wrapped.call_count, 1)
            canonical_input, identity = wrapped.call_args.args
            self.assertEqual(canonical_input, legacy)
            state, record = self.snapshots(job_id)
            self.assertEqual(record['outputs'][task['id']], legacy)
            legacy_result = worker_result_hook.wrap_output(legacy, identity)
            self.assertEqual(len(observed), 1)
            actual_result = observed[0]
            self.assertEqual(legacy_result['_worker_result'],
                             actual_result['_worker_result'])
            self.assertEqual(worker_result_commit._evidence(
                legacy_result['_worker_result']), state['evidence'][0])
            self.assertEqual(state['evidence'][0]['command_id'],
                             task['id']+':1:p1')
            self.assertEqual(len(state['evidence']),1)
            self.assertEqual(record['steps'][0]['attempts'],1)

    def test_legacy_file_and_scheduler_have_byte_identical_worker_result(self):
        source = self.root/'equivalent.txt'
        source.write_text('The contract must be filed by 2027-12-01.',
                          encoding='utf-8')
        self._assert_byte_identical_worker_result({
            'id':'read','agent':'file','depends':[],
            'input':{'path':str(source),'operation':'extract_obligations'},
        }, 'Extract obligations from this local file.', file_root=True)

    def test_legacy_media_and_scheduler_have_byte_identical_worker_result(self):
        source = self.root/'files'/'source.png'
        source.parent.mkdir(parents=True,exist_ok=True)
        source.write_bytes(b'fixed mock image bytes')
        video = self.root/'mock-render.mp4'
        video.write_bytes(b'fixed mock MP4 payload')
        metadata = {'width':1280,'height':720,'duration':4.0,'has_audio':False}
        render = {'state':'done','text':'Local video rendered',
                  'file':str(video),'sha256':task_results.file_digest(video),
                  'media':metadata}
        self._assert_byte_identical_worker_result({
            'id':'video','agent':'media','depends':[],
            'input':{'image':str(source),
                     'image_sha256':task_results.file_digest(source),
                     'duration':4},
        }, 'Create a local video from this image.', render=render)


    def test_video_admin_entry_uses_canonical_rid_not_legacy_execute(self):
        data={'scenes':[{'caption':'First scene','duration':3}]}
        command='görev akışı video: '+json.dumps(data)
        rid='exact-video-request'
        with patch.object(requests_state._current,'get',
                          return_value=(self.owner,rid)), \
             patch.object(task_queue,'scheduler_active',return_value=True), \
             patch.object(media_tools,'prepare',return_value=data), \
             patch.object(canonical_goal_flow,'try_create',
                          return_value=('aabbccddeeff0011','Admitted')) as admitted, \
             patch.object(task_agents,'execute',
                          side_effect=AssertionError('Old video execute forbidden')) as legacy:
            self.assertEqual(task_agents.handle(self.owner,command),'Admitted')
            admitted.assert_called_once_with(
                self.owner,rid,command,direct_tasks=[
                    {'id':'video','agent':'media','depends':[], 'input':data},
                ])
            legacy.assert_not_called()

    def test_direct_video_prefix_does_not_start_old_job(self):
        data={'scenes':[{'caption':'First scene','duration':3}]}
        command='video üret '+json.dumps(data)
        with patch.object(requests_state._current,'get',
                          return_value=(self.owner,'video-rid')), \
             patch.object(task_queue,'scheduler_active',return_value=True), \
             patch.object(media_tools,'prepare',return_value=data), \
             patch.object(canonical_goal_flow,'try_create',
                          return_value=('aabbccddeeff0011','Admitted')) as admitted, \
             patch.object(task_agents,'execute',
                          side_effect=AssertionError('Old video execute forbidden')):
            self.assertEqual(task_agents.handle(self.owner,command),'Admitted')
            self.assertEqual(admitted.call_count,1)

    def test_no_request_rid_or_scheduler_means_no_legacy_video_fallback(self):
        data={'scenes':[{'caption':'First scene','duration':3}]}
        command='video üret '+json.dumps(data)
        with patch.object(requests_state._current,'get',return_value=None), \
             patch.object(media_tools,'prepare',return_value=data), \
             patch.object(task_agents,'execute') as legacy:
            with self.assertRaises(PermissionError):
                task_agents.handle(self.owner,command)
            legacy.assert_not_called()

    def test_direct_media_only_and_no_new_legacy_media_file_plan(self):
        with self.assertRaises(ValueError):
            canonical_goal_flow.try_create(self.owner,'rid','video',direct_tasks=[
                {'id':'bad','agent':'file','input':{'path':'x','operation':'extract_obligations'}},
            ])
        with self.assertRaises(ValueError):
            canonical_goal_flow.try_create(self.owner,'rid','Summarize my emails',
                direct_tasks=[{'id':'video','agent':'media','input':{
                    'scenes':[{'caption':'Scene','duration':3}]}}])
        for agent, data in (
            ('media', {'scenes':[{'caption':'Scene','duration':3}]}),
            ('file', {'path':'x.txt','operation':'extract_obligations'}),
        ):
            with self.subTest(agent):
                with self.assertRaises(ValueError):
                    goal_executor._parse(json.dumps({'tasks':[{
                        'id':'step','agent':agent,'input':data,
                    }]}))
        self.assertNotIn('media',task_agents._REPLAY_SAFE)

if __name__=='__main__':
    unittest.main()
