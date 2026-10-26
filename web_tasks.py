"""UI bridge operations with explicit owning-runtime dependencies."""
from __future__ import annotations

class WebTasks:

    def team_snapshot(self) -> dict:
        from modules import team_center
        return team_center.snapshot(self._runtime._p().slug)

    def team_save(self, members: list, revision=None) -> list:
        from modules import team_center
        return team_center.save_members(self._runtime._p().slug, members, revision)

    def team_schedule(self, tasks: list, instruction: str, seconds: int=0, repeat_seconds: int=0, cron: str='') -> str:
        from modules import task_queue
        return task_queue.enqueue(self._runtime._p().slug, tasks, instruction, seconds, repeat_seconds, cron)

    def team_script_schedule(self, tasks: list, instruction: str='', cron: str='') -> str:
        """Schedule an explicit task DAG without a planner/model round-trip."""
        from modules import task_queue
        return task_queue.enqueue_script(self._runtime._p().slug, tasks, instruction, cron)

    def team_queue_run_now(self, identity: str) -> str:
        from modules import task_queue
        return task_queue.run_now(self._runtime._p().slug, identity)

    def team_queue_cancel(self, identity: str) -> bool:
        from modules import task_queue
        task_queue.cancel(self._runtime._p().slug, identity)
        return True

    def team_queue_edit(self, identity: str, operation: str, repeat_seconds=None) -> bool:
        from modules import task_queue
        return task_queue.configure(self._runtime._p().slug,identity,operation=operation,repeat_seconds=repeat_seconds)

    def team_control(self, kind: str, identity: str, action: str, control: str='', answer: str='', approval_id: str='') -> str:
        from modules import goal_executor, task_agents, service_store
        runtime=self._runtime;profile=runtime._p();owner=profile.slug
        service_store.identity(owner)
        if not isinstance(identity,str) or not runtime.re.fullmatch('[a-f0-9]{12,32}',identity):raise ValueError('Görev kimliği geçersiz.')
        if action not in {'cancel','resume','approve','answer'}:raise ValueError('Görev işlemi geçersiz.')
        if not isinstance(answer,str) or len(answer)>2000:raise ValueError('Yanıt fazla uzun.')
        if kind=='goal':
            job=goal_executor.latest(owner)
            if not job or job['id']!=identity:raise ValueError('Seçilen hedef son hedef değil; başka hedefe işlem uygulanmadı.')
            if action=='cancel':return goal_executor.cancel_job(owner,identity)
            if not isinstance(control,str) or goal_executor.control_key(job)!=control:raise ValueError('Görev değişmiş; önce yenile.')
            if action=='approve' and job['state']!='approval':raise ValueError('Hedef onay beklemiyor.')
            if action=='answer' and (job['state']!='question' or not answer.strip()):raise ValueError('Hedef yanıt beklemiyor veya yanıt boş.')
            if action=='resume' and job['state'] not in {'paused','question','running'}:raise ValueError('Bu hedef bu düğmeyle sürdürülemez.')
            verb={'resume':'devam','approve':'onayla','answer':'yanıtla'}[action]
            command=f'hedef {verb} {identity} {control}'+(': '+answer.strip() if action=='answer' else '')
        elif kind=='task':
            job=task_agents._load(owner,identity)
            if action=='cancel':
                task_agents.cancel_job(owner,identity)
                return 'Seçilen görev için iptal kaydedildi.'
            if goal_executor.control_key(job)!=control:raise ValueError('Görev veya bekleyen işlem değişmiş; önce yenile.')
            if action=='resume':command='görev devam '+identity
            elif action=='approve':
                step=next((s for s in job['tasks'] if s['state']=='approval'),None)
                receipt=job['outputs'].get(step['id'],{}) if step else {}
                if not step or receipt.get('id')!=approval_id or not runtime.re.fullmatch('[a-f0-9]{16}',approval_id or ''):
                    raise ValueError('Onay seçilen görevin bekleyen işlemiyle eşleşmiyor.')
                if step['agent'] not in {'publish','browser'}:raise ValueError('Bu işlem sohbetten yönetilmeli.')
                command=('işlem onayla ' if step['agent']=='publish' else 'tarayıcı onayla ')+approval_id
            else:raise ValueError('Bu görev türü serbest yanıt kabul etmiyor.')
        else:raise ValueError('Görev türü geçersiz.')
        import uuid
        if runtime.engine.submit(command,'yazı',profile.name,rid=uuid.uuid4().hex) is False:raise ValueError('Kontrol isteği kuyruğa alınamadı.')
        return 'Kontrol isteği seçilen görev için Jarvis’e iletildi.'

    def team_verify(self, kind: str, identity: str) -> dict:
        from modules import goal_executor, goal_tools, task_agents, task_results, service_store
        owner = self._runtime._p().slug
        service_store.identity(owner)
        if not isinstance(identity,str) or not self._runtime.re.fullmatch('[a-f0-9]{12,32}',identity):
            raise ValueError('Görev kimliği geçersiz.')
        if kind == 'task':
            job = task_agents._load(owner,identity)
            verify = lambda output: task_results.verify(output,owner=owner)
        elif kind == 'goal':
            from modules import execution_record
            try:
                job = execution_record.load(goal_executor._root(owner),owner,identity)
            except PermissionError:
                raise ValueError('Görev sahibi eşleşmiyor.') from None
            except (OSError,ValueError):
                raise ValueError('Görev kaydı geçersiz.') from None
            verify = lambda output: goal_tools.verify(output,owner)
        else:
            raise ValueError('Görev türü geçersiz.')
        outputs = {key:value for key,value in job.get('outputs',{}).items() if value.get('state')=='done'}
        if not outputs:
            return {'ok':False,'message':'Doğrulanacak tamamlanmış çıktı yok.'}
        failed = []
        for key,value in outputs.items():
            try:
                verify(value)
            except (ValueError,PermissionError,OSError,KeyError,TypeError):
                failed.append(key)
        return {'ok':not failed,'checked':len(outputs),'failed':failed,
                'message':'Yerel kanıtlar denetlendi. İçerik doğruluğu ve hesapların güncel durumu bu kontrolün kapsamında değil.'}

    def task_add(self, text: str, when: str='') -> dict:
        runtime = self._runtime
        return runtime.tasks.add(runtime._p(), text, when)

    def task_toggle(self, tid: int) -> bool:
        runtime = self._runtime
        runtime.tasks.toggle(runtime._p(), int(tid))
        return True

    def task_delete(self, tid: int) -> bool:
        runtime = self._runtime
        runtime.tasks.delete(runtime._p(), int(tid))
        return True

    def task_clear_done(self) -> int:
        runtime = self._runtime
        return runtime.tasks.clear_done(runtime._p())

    def note_add(self, text: str, photo_path: str='', title: str='') -> bool:
        runtime = self._runtime
        from modules import note_images
        note_images.add(runtime._p(), text, photo_path, title)
        return True

    def note_image(self, nid: int) -> str:
        runtime = self._runtime
        from modules import note_images
        return note_images.preview(runtime._p(), nid)

    def note_delete(self, nid: int) -> bool:
        runtime = self._runtime
        runtime._p().delete_note_item(int(nid))
        return True

    def event_add(self, title: str, when: str) -> dict:
        """when: 'YYYY-MM-DD' ya da 'YYYY-MM-DDTHH:MM'."""
        runtime = self._runtime
        if not runtime.re.match('^\\d{4}-\\d{2}-\\d{2}(T\\d{2}:\\d{2})?$', when or ''):
            raise ValueError('Tarih biçimi geçersiz')
        runtime.datetime.fromisoformat(when)
        if not title.strip():
            raise ValueError('Etkinlik başlığı gerekli')
        return runtime._p().add_event(title.strip(), when)

    def event_add_text(self, text: str, details: bool=False) -> str | dict:
        """'yarın 15'te toplantı' gibi serbest metinden etkinlik ekler."""
        runtime = self._runtime
        when, title = runtime.whenmod.parse_when(text, runtime.datetime.now())
        if not when:
            raise ValueError("Tarih ya da saat bulamadım. Örn: yarın 15'te toplantı")
        ev = runtime._p().add_event(title or text, when)
        return {**ev, 'label': f"{ev['title']} · {runtime.whenmod.describe(when)}"} if details else f"{ev['title']} · {runtime.whenmod.describe(when)}"

    def event_delete(self, eid: int) -> bool:
        runtime = self._runtime
        return runtime._p().delete_event(int(eid))

