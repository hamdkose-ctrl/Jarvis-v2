"""Files page actions; dependencies are provided by the owning bridge."""
from __future__ import annotations

import threading

from modules.diagnostics import record_failure as _record_failure

_INDEXING = threading.Event()

class WebFiles:

    def screen_capture(self) -> dict:
        from modules import screen_capture
        return screen_capture.capture(self._runtime)

    def files_list(self, force: bool=False) -> dict:
        runtime = self._runtime
        from modules import nxapi
        return nxapi.list_files(force=bool(force))

    def files_search(self, query: str) -> list:
        """Belge içeriğinde arama (Dosyalar arama kutusu). Jarvis'e yüklenenler arka planda dizinlenir; isabet yoksa boş liste."""
        runtime = self._runtime
        from modules import nxapi
        owner = runtime._p()
        self._index_uploads(owner)
        rows = []
        for hit in runtime.kb.file_hits(owner, str(query)[:200]):
            row = nxapi.describe_file(hit["path"])
            if row:
                rows.append({**row, "snippet": hit["snippet"], "hit_where": hit["where"]})
        return rows

    def _index_uploads(self, owner) -> None:
        if _INDEXING.is_set():
            return
        _INDEXING.set()
        runtime = self._runtime

        def work():
            try:
                from modules import nxapi
                runtime.kb.index_files(owner, [x for x in nxapi.FILES_DIR.rglob("*") if x.is_file()])
            except OSError:
                _record_failure('web_files.py:_index_uploads')
            finally:
                _INDEXING.clear()
        threading.Thread(target=work, daemon=True, name="belge-dizin").start()

    def file_inventory_run(self, folder: str) -> dict:
        """Salt-okunur klasör envanteri özeti (Dosyalar › Envanter raporu).

        İzinli kökler file_worker.allowed_roots ile aynıdır; rapor hiçbir dosyaya
        dokunmaz. Arayüzde köklü yeniden tasarım beklenirken API sözleşmesi
        sabittir: düğme taşınırsa bu yöntem adları korunur.
        """
        from modules import file_inventory
        report = file_inventory.build_report(str(folder))
        def row(item: dict) -> dict:
            return {'name': item.get('name', ''), 'path': item.get('path', ''),
                    'size': item.get('size', 0), 'ext': item.get('ext', '')}
        return {'folder': report.folder, 'total_files': report.total_files,
                'truncated': report.truncated, 'by_extension': dict(report.by_extension),
                'duplicate_groups': [[row(x) for x in g] for g in report.duplicate_groups],
                'similar_groups': [[row(x) for x in g] for g in report.similar_name_groups],
                'empty': [row(x) for x in report.empty_file_candidates],
                'old': [row(x) for x in report.old_file_candidates],
                'temp': [row(x) for x in report.temp_name_candidates]}

    def file_inventory_excel(self, folder: str) -> dict:
        """Envanter raporunu kaynak klasöre yeni bir .xlsx olarak yazar (üzerine yazmaz)."""
        from modules import file_inventory
        report = file_inventory.build_report(str(folder))
        path = file_inventory.export_xlsx(report)
        return {'path': path, 'total_files': report.total_files,
                'duplicates': len(report.duplicate_groups),
                'similar': len(report.similar_name_groups),
                'empty': len(report.empty_file_candidates),
                'old': len(report.old_file_candidates),
                'temp': len(report.temp_name_candidates)}

    def file_do(self, path: str, action: str) -> str:
        runtime = self._runtime
        from modules import nxapi
        cmd = nxapi.action_command(str(path), str(action))
        accepted = runtime.engine.submit(cmd, 'yazı', runtime._p().name)
        if accepted is False:
            raise ValueError('İstek kuyruğa alınmadı; işlemi yeniden gönder.')
        return cmd

    def file_open(self, path: str, reveal: bool=False) -> bool:
        runtime = self._runtime
        from modules import nxapi
        return nxapi.open_path(str(path), bool(reveal))

    def folder_pick(self) -> dict:
        runtime = self._runtime
        from modules import nxapi
        from modules import ui_jobs
        owner = runtime._p().slug
        def choose():
            p = nxapi.pick_folder()
            return {'path': p, 'count': len(nxapi.folder_files(p)) if p else 0, 'name': runtime.Path(p).name if p else ''}
        return ui_jobs.start(owner, 'folder_pick', choose)

    def folder_import(self, path: str) -> dict:
        runtime = self._runtime
        from modules import nxapi
        return nxapi.import_folder(str(path))

    def files_dir_open(self) -> bool:
        runtime = self._runtime
        from modules import nxapi
        nxapi.FILES_DIR.mkdir(parents=True, exist_ok=True)
        return nxapi.open_path(str(nxapi.FILES_DIR))
