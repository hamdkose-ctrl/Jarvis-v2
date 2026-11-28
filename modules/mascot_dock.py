"""Compact desktop access to the existing Jarvis bridge; Tk stays on its owning thread."""
from __future__ import annotations

import queue
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from modules.diagnostics import record_failure

STATUS = {
    "idle": "Hazır", "greeting": "Hazır", "listening": "Dinliyorum",
    "thinking": "Düşünüyorum", "working": "İşlem sürüyor", "speaking": "Konuşuyorum",
}
JOB_STATUS = {
    "running": "Sürüyor", "queued": "Sırada", "approval": "Onay bekliyor",
    "question": "Yanıt bekliyor", "paused": "Duraklatıldı", "done": "Tamamlandı",
    "partial": "Kısmi", "failed": "Başarısız", "cancelled": "İptal edildi",
    "blocked": "Engellendi", "interrupted": "Kesintiye uğradı",
}
TERMINAL = {"done", "partial", "failed", "blocked", "cancelled"}
LINK = re.compile(r"https?://[^\s<>\])]+")
MAX_FILE_BYTES = 200_000_000
BG, CARD, BORDER = "#101a24", "#172634", "#293d4e"
TEXT, MUTED, ACCENT = "#f3f7fc", "#adc2d4", "#8fe0e7"


def parse_hotkey(value: str) -> tuple[int, int] | None:
    parts = str(value).upper().replace(" ", "").split("+")
    modifiers = {"ALT": 1, "CTRL": 2, "SHIFT": 4}
    keys = parts[:-1]
    if (not 1 <= len(keys) <= 3 or len(set(keys)) != len(keys)
            or any(k not in modifiers for k in keys)
            or not re.fullmatch("[A-Z0-9]", parts[-1])):
        return None
    return 0x4000 | sum(modifiers[k] for k in keys), ord(parts[-1])


def hotkey_loop(shortcut, stop, events):
    """Own the WM_HOTKEY queue on a dedicated thread, never on Tk's message pump."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    msg = wintypes.MSG()
    if not user32.RegisterHotKey(None, 1, *shortcut):
        events.put("hotkey_unavailable")
        return
    events.put("hotkey_registered")
    try:
        while not stop.wait(.05):
            if user32.PeekMessageW(ctypes.byref(msg), None, 0x0312, 0x0312, 1):
                events.put("compose")
    finally:
        user32.UnregisterHotKey(None, 1)


def file_command(text, paths):
    """Use the same quoted-path command syntax as the web composer."""
    if not paths:
        return text
    if any('"' in str(path) or "\r" in str(path) or "\n" in str(path) for path in paths):
        raise ValueError("Dosya adı bu komutta kullanılamıyor.")
    names = " ".join(f'"{path}"' for path in paths)
    return names + " " + (text or "dosyasını özetle")


def reply_links(text):
    links = []
    for match in LINK.findall(text):
        link = match.rstrip(".,;:!?\"'")
        try:
            parts = urlsplit(link)
            if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
                links.append(link)
        except ValueError:
            continue
    return list(dict.fromkeys(links))[:8]


def eligible_job_actions(job):
    state = job.get("record_state", job.get("state"))
    if state == "approval" and job.get("approval"):
        return ("approve", "cancel")
    if state == "question":
        return ("answer", "cancel") if job.get("kind") == "goal" else ("cancel",)
    if state in {"running", "queued", "paused"}:
        return ("cancel",)
    return ()


class MascotDock:
    """Native composer and result card attached to the mascot, with a bounded UI event pump."""

    def __init__(self, mascot):
        self.mascot = mascot
        self.runtime = mascot.runtime
        self.messages = self.runtime.hub.subscribe(desktop=True)
        self.local = queue.Queue()
        self.owner = self.runtime._p().slug
        self.last_reply = ""
        self.notice = ""
        self.badge = ""
        self.active_rid = ""
        self.pending = False
        self.attachment = None
        self.selected_job = None
        self.jobs = []
        self.files = []
        self.file_inflight = False
        self.job_fingerprints = None
        self.next_jobs = time.monotonic() + 2
        self.opened_at = time.time()
        self.jobs_inflight = False
        self.generation = 0
        self.view = "reply"
        self.hotkey_registered = False
        self.stop_key = None
        self.key_thread = None
        self.panel = None
        self.hotkey = str(mascot._settings().get("mascot_hotkey") or "Ctrl+Alt+J")
        self._register_hotkey()

    def _register_hotkey(self):
        if self.stop_key:
            self.stop_key.set()
        if self.key_thread:
            self.key_thread.join(timeout=.15)
        self.hotkey_registered = False
        self.stop_key = threading.Event()
        shortcut = parse_hotkey(self.hotkey)
        if shortcut and sys.platform.startswith("win"):
            self.key_thread = threading.Thread(target=hotkey_loop, args=(shortcut, self.stop_key, self.local),
                                               name="jarvis-mascot-hotkey", daemon=True)
            self.key_thread.start()

    def close(self):
        if self.stop_key:
            self.stop_key.set()
        self.runtime.hub.unsubscribe(self.messages, desktop=True)

    def _create(self):
        import tkinter as tk

        self.panel = tk.Toplevel(self.mascot.root)
        self.panel.withdraw()
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        self.panel.configure(bg=BORDER)
        self.panel.bind("<Escape>", lambda _e: self.panel.withdraw())
        self.panel.bind("<Control-Return>", lambda _e: self.send())
        body = tk.Frame(self.panel, bg=BG, padx=16, pady=13)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(body, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Jarvis", bg=BG, fg=TEXT, font=("Segoe UI", 14, "bold")).pack(side="left")
        self._button(head, "Kapat", self.panel.withdraw).pack(side="right")
        self.status = tk.Label(body, bg=BG, fg=ACCENT, anchor="w", font=("Segoe UI", 10))
        self.status.pack(fill="x", pady=(5, 9))
        actions = tk.Frame(body, bg=BG)
        actions.pack(fill="x")
        for label, command in (("Konuş", self.listen), ("Yanıt", lambda: self.switch("reply")),
                               ("Son işler", self.show_jobs)):
            self._button(actions, label, command).pack(side="left", padx=(0, 5))
        self.speech_button = self._button(actions, "Sesi kes", self.stop_speech)
        self.cancel_button = self._button(actions, "İsteği durdur", self.stop_turn)
        self.attachment_label = tk.Label(body, bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9))
        self.attachment_label.pack(fill="x", pady=(5, 1))
        composer = tk.Frame(body, bg=BG)
        composer.pack(fill="x")
        self._button(composer, "Dosya ekle", self.pick_file).pack(side="left", padx=(0, 5))
        self.entry = tk.Entry(composer, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=("Segoe UI", 11), highlightthickness=1, highlightbackground=BORDER)
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda _e: self.send())
        self.entry.bind("<Button-1>", lambda _e: self._focus_entry())
        self._button(composer, "Gönder", self.send, accent=True).pack(side="right", padx=(5, 0))
        self.results = tk.Frame(body, bg=CARD, pady=4)
        self.results.pack(fill="both", expand=True, pady=(12, 9))
        self.footer = tk.Frame(body, bg=BG)
        self.footer.pack(fill="x")
        self._button(self.footer, "Komut Merkezi", self.open_console).pack(side="right")
        self._button(self.footer, "Dosya bul", self.find_files).pack(side="left")
        self._render()
        self._update_actions()

    @staticmethod
    def _button(parent, label, command, accent=False):
        import tkinter as tk

        return tk.Button(parent, text=label, command=command, bg=ACCENT if accent else CARD,
                         fg=BG if accent else TEXT, activebackground=BORDER, activeforeground=TEXT,
                         font=("Segoe UI", 9, "bold"), relief="flat", padx=8, pady=5,
                         highlightthickness=1, highlightbackground=BORDER, takefocus=True)

    def open(self, *, focus=False):
        from modules.mascot_window import clamp_position, set_no_activate, windows_monitors

        if self.panel is None:
            self._create()
        self.badge = ""
        if self.panel.winfo_viewable() and not focus:
            return
        self.panel.update_idletasks()
        w = min(500, max(418, self.panel.winfo_reqwidth()))
        h = min(475, max(306, self.panel.winfo_reqheight()))
        x0, y0 = self.mascot.window.winfo_x(), self.mascot.window.winfo_y()
        screens = windows_monitors(self.mascot.root)
        x, y = clamp_position(x0 - w - 12, y0 + self.mascot.size[1] - h, w, h, screens)
        self.panel.geometry(f"{w}x{h}+{x}+{y}")
        set_no_activate(self.panel, not focus)
        self.panel.deiconify()
        if focus:
            self.entry.focus_force()

    def _update_actions(self):
        for widget, shown in ((self.speech_button, self.mascot._state == "speaking"),
                              (self.cancel_button, bool(self.active_rid)
                               and self.mascot._state in {"thinking", "working"})):
            if shown and not widget.winfo_manager():
                widget.pack(side="right", padx=(3, 0))
            elif not shown and widget.winfo_manager():
                widget.pack_forget()

    def open_console(self):
        if self.panel is not None:
            self.panel.withdraw()
        self.runtime._show_main()

    def open_badge(self):
        if self.badge == "İşler":
            self.show_jobs()
        else:
            self.switch("reply")
        self.open(focus=True)

    def _focus_entry(self):
        from modules.mascot_window import set_no_activate

        set_no_activate(self.panel, False)
        self.entry.focus_force()

    def change_shortcut(self):
        from tkinter import simpledialog

        if self.panel is None:
            self._create()
        value = simpledialog.askstring("Klavye kısayolu", "Bir tuş birleşimi gir (Ctrl+Alt+J).",
                                       initialvalue=self.hotkey, parent=self.mascot.window)
        if value is None:
            return
        if parse_hotkey(value) is None:
            self._set_notice("Kısayol için Ctrl, Alt veya Shift ile bir harf ya da rakam seç.")
            self.open(focus=True)
            return
        if value != self.hotkey:
            self.hotkey = value
            self.mascot._save(mascot_hotkey=value)
            self._register_hotkey()

    def _set_notice(self, text):
        self.notice = str(text)
        if self.panel is not None:
            self.status.configure(text=(self.notice or self._status_text())[:120])

    def _status_text(self):
        flags = self.runtime.engine.flags
        if flags.get("sleep"):
            return "Uykuda"
        if self.mascot._state == "idle" and not flags.get("mic", True):
            return "Mikrofon kapalı"
        return STATUS.get(self.mascot._state, "Hazır")

    def listen(self):
        try:
            if not self.runtime.engine.flags.get("mic", True):
                self._set_notice("Mikrofon kapalı.")
            else:
                if self.runtime.engine.flags.get("sleep"):
                    self.runtime.bridge.sleep(False)
                accepted = self.runtime.bridge.listen_once()
                self._set_notice("Dinleme başlatılıyor…" if accepted else "Mikrofon kapalı.")
        except ValueError as exc:
            self._set_notice(exc)

    def stop_speech(self):
        self.runtime.bridge.stop_speaking()
        self._set_notice("Ses durduruldu.")

    def stop_turn(self):
        self._set_notice(self.runtime.bridge.stop_task()["msg"])

    def toggle_mic(self):
        state = self.runtime.bridge.set_flag("mic", not self.runtime.engine.flags.get("mic", True))
        self._set_notice("Mikrofon açık." if state.get("mic") else "Mikrofon kapalı.")

    def pick_file(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(parent=self.panel, title="Jarvis için dosya seç")
        if path:
            self.attachment = Path(path)
            self.attachment_label.configure(text=f"Ek · {self.attachment.name}   (Kaldırmak için tıkla)")
            self.attachment_label.bind("<Button-1>", lambda _e: self.clear_file())

    def clear_file(self):
        self.attachment = None
        if self.panel is not None:
            self.attachment_label.configure(text="")

    def _run(self, tag, function, callback=None):
        profile = self.runtime._p()
        if profile.slug != self.owner:
            return
        generation = self.generation

        def work():
            token = self.runtime._bridge_profile.set(profile)
            try:
                if self.runtime.engine.pc_profile().slug != profile.slug:
                    raise ValueError("Etkin kullanıcı değişti.")
                result = function()
                self.local.put((tag, profile.slug, generation, callback, result, None))
            except Exception as exc:  # noqa: BLE001 - background UI action stays recoverable
                record_failure("modules/mascot_dock.py:" + tag)
                error = str(exc) if isinstance(exc, ValueError) else "İşlem tamamlanamadı."
                self.local.put((tag, profile.slug, generation, callback, None, error))
            finally:
                self.runtime._bridge_profile.reset(token)

        threading.Thread(target=work, name="jarvis-mascot-" + tag, daemon=True).start()

    def send(self):
        text, attachment = self.entry.get().strip(), self.attachment
        if self.pending or (not text and attachment is None):
            return
        if self.view == "job" and self.selected_job and self.selected_job.get("state") == "question" and not attachment:
            self.control_job("answer", text)
            return
        rid = uuid.uuid4().hex
        self.active_rid, self.pending = rid, True

        def submit():
            from modules import nxapi

            path = None
            if attachment is not None:
                path = nxapi.allowed(attachment)
                if path is None or not path.is_file():
                    raise ValueError("Belgeler, Masaüstü veya Jarvis dosyalarından bir dosya seç.")
                if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
                    raise ValueError("Dosya boş veya 200 MB’tan büyük.")
            return self.runtime.bridge.send(file_command(text, [path] if path else []), rid)

        def sent(accepted):
            if self.entry.get().strip() == text:
                self.entry.delete(0, "end")
            if self.attachment == attachment:
                self.clear_file()
            self.switch("reply")
            if self.active_rid == rid:
                if not accepted:
                    self.active_rid = ""
                self._set_notice("İstek alındı…" if accepted else "Kontrol isteği iletildi.")

        self._run("send", submit, sent)

    def find_files(self):
        from tkinter import simpledialog

        if self.file_inflight:
            return
        query = simpledialog.askstring("Dosya bul", "Dosya adı veya içerikten bir kelime yaz.", parent=self.panel)
        if not query or not query.strip():
            return
        self.file_inflight = True
        term = query.strip().casefold()
        self._set_notice("Dosyalar aranıyor…")

        def lookup():
            rows = self.runtime.bridge.files_list().get("files", [])
            named = [row for row in rows if term in str(row.get("name", "")).casefold()]
            indexed = self.runtime.bridge.files_search(query) if len(named) < 5 else []
            return list({row["path"]: row for row in [*named, *indexed] if row.get("path")}.values())[:5]

        def found(rows):
            self.files = rows
            self.switch("files")
            self._set_notice("Dosyalar" if rows else "Eşleşen dosya bulunamadı.")

        self._run("files", lookup, found)

    def _file_action(self, path, *, reveal=False):
        self._run("file-open", lambda: self.runtime.bridge.file_open(path, reveal))

    def show_jobs(self):
        self.switch("jobs")
        self._refresh_jobs()

    def _refresh_jobs(self):
        if self.jobs_inflight:
            return
        self.jobs_inflight = True
        from modules import team_center

        owner = self.owner
        self._run("jobs", lambda: team_center.jobs_snapshot(owner)[0], self._receive_jobs)

    def _receive_jobs(self, snapshot):
        rows = [job for job in snapshot if job.get("id")]
        seen = {(job["kind"], job["id"]): job.get("state") for job in rows}
        if self.job_fingerprints is not None:
            for job in rows:
                old = self.job_fingerprints.get((job["kind"], job["id"]))
                was_active = old in {"running", "queued", "paused", "approval", "question"}
                new_job = old is None and (job.get("created", 0) or 0) >= self.opened_at
                if (was_active or new_job) and job.get("state") in TERMINAL | {"approval", "question"} and old != job.get("state"):
                    self._set_notice("İş güncellendi · " + JOB_STATUS.get(job["state"], "Ayrıntı hazır"))
                    self.badge = "İşler"
                    if job.get("state") == "done":
                        self.mascot.celebrate()
                    break
        old_rows = self.jobs
        self.job_fingerprints, self.jobs = seen, rows
        if self.panel is not None and self.view == "jobs" and old_rows != rows:
            self._render()
        elif self.view == "job" and self.selected_job:
            selected = self.selected_job
            current = next((j for j in rows if (j["kind"], j["id"]) == (selected["kind"], selected["id"])), None)
            if current != selected:
                self.selected_job = current
                self.switch("job" if current else "jobs")

    def control_job(self, action, answer=""):
        job = self.selected_job
        if not job or action not in eligible_job_actions(job) or self.pending:
            return
        self.pending = True
        if action == "answer" and not answer.strip():
            self.pending = False
            self._set_notice("Önce aşağıya yanıtını yaz.")
            return

        def done(message):
            self._set_notice(message)
            if action == "answer":
                self.entry.delete(0, "end")
            self._refresh_jobs()

        self._run("control", lambda: self.runtime.bridge.team_control(
            job["kind"], job["id"], action, job.get("control", ""), answer, job.get("approval_id", "")), done)

    def _download(self, job, step, name):
        from tkinter import filedialog
        import base64

        dest = filedialog.asksaveasfilename(parent=self.panel, initialfile=name)
        if not dest:
            return

        def save():
            payload = self.runtime.bridge.team_artifact(job["kind"], job["id"], step["id"], name)
            if payload.get("owner") != self.runtime.engine.pc_profile().slug:
                raise ValueError("Etkin kullanıcı değişti.")
            data = base64.b64decode(payload["content"], validate=True)
            target = Path(dest)
            created = False
            try:
                # The picker confirms a destination; never replace a concurrent arrival.
                with target.open("xb") as stream:
                    created = True
                    stream.write(data)
            except FileExistsError as exc:
                raise ValueError("Bu adla dosya var. Farklı bir ad seç.") from exc
            except OSError:
                if created:
                    target.unlink(missing_ok=True)
                raise
            return target.name

        self._run("download", save, lambda name: self._set_notice(f"Kaydedildi · {name}"))

    def switch(self, view):
        self.view = view
        if self.panel is not None:
            self._render()

    def _render(self):
        import tkinter as tk

        for widget in self.results.winfo_children():
            widget.destroy()
        self.status.configure(text=(self.notice or self._status_text())[:120])
        if self.view == "files":
            if not self.files:
                self._result_text("Eşleşen dosya bulunamadı.")
            for file in self.files:
                row = tk.Frame(self.results, bg=CARD)
                row.pack(fill="x", padx=5, pady=1)
                tk.Label(row, text=file["name"][:34], bg=CARD, fg=TEXT).pack(side="left")
                self._button(row, "Klasörde", lambda p=file["path"]: self._file_action(p, reveal=True)).pack(side="right")
                self._button(row, "Aç", lambda p=file["path"]: self._file_action(p)).pack(side="right")
            return
        if self.view == "jobs":
            for job in self.jobs[:6]:
                label = JOB_STATUS.get(job.get("state"), "İş")
                title = " ".join(str(job.get("request", "")).split())[:45]
                self._button(self.results, f"{label}  ·  {title}", lambda j=job: self._select(j)).pack(fill="x", padx=5, pady=2)
            if not self.jobs:
                self._result_text("Yakın zamanda kayıtlı iş yok.")
            return
        if self.view == "job" and self.selected_job:
            job = self.selected_job
            steps = job.get("steps", [])
            status = JOB_STATUS.get(job.get("state"), "İş durumu")
            message = job.get("approval") or job.get("question") or "\n\n".join(
                str(step["text"]) for step in steps if step.get("text")) or job.get("request") or ""
            self._result_text(status + "\n\n" + message)
            commands = tk.Frame(self.results, bg=CARD)
            commands.pack(fill="x", padx=5)
            labels = {"approve": "Onayla", "cancel": "İptal et", "answer": "Yanıtla"}
            self._button(commands, "Ayrıntı", lambda: self._open_job_in_console(job)).pack(side="right")
            for action in eligible_job_actions(job):
                handler = self._focus_entry if action == "answer" else (lambda a=action: self.control_job(a))
                self._button(commands, labels[action], handler).pack(side="left", padx=2)
            downloads = [(step, name) for step in steps for name in step.get("downloads", [])]
            for step, name in downloads[:3]:
                self._button(self.results, f"Kaydet · {name[:46]}", lambda s=step, n=name: self._download(job, s, n)).pack(fill="x", padx=5)
            return
        self._result_text(self.last_reply or "Konuşabilir, yazabilir veya bir dosya seçebilirsin.")
        if self.last_reply:
            strip = tk.Frame(self.results, bg=CARD)
            strip.pack(fill="x", padx=5)
            self._button(strip, "Kopyala", self.copy_reply).pack(side="left")
            for i, url in enumerate(reply_links(self.last_reply)[:3], 1):
                self._button(strip, f"Kaynak {i}", lambda link=url: self._open_link(link)).pack(side="left", padx=3)

    def _open_job_in_console(self, job):
        ident, kind = job.get("id", ""), job.get("kind", "")
        if (self.runtime.engine.pc_profile().slug == self.owner and kind in {"goal", "task"}
                and re.fullmatch(r"[a-f0-9]{12,32}", ident)):
            self.panel.withdraw()
            self.runtime._self_action("nav", f"team|{kind}-{ident}")

    def _open_link(self, url):
        import webbrowser

        if self.runtime.engine.pc_profile().slug == self.owner and url in reply_links(self.last_reply):
            webbrowser.open(url)

    def _result_text(self, value):
        import tkinter as tk

        body = tk.Frame(self.results, bg=CARD)
        body.pack(fill="both", expand=True)
        box = tk.Text(body, height=7, width=44, wrap="word", bg=CARD, fg=TEXT, relief="flat",
                      padx=8, pady=6, font=("Segoe UI", 10), cursor="arrow", takefocus=True,
                      highlightthickness=0)
        scroll = tk.Scrollbar(body, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        box.insert("1.0", value)
        box.configure(state="disabled")

    def _select(self, job):
        self.selected_job = job
        self.switch("job")

    def copy_reply(self):
        self.panel.clipboard_clear()
        self.panel.clipboard_append(self.last_reply)
        self._set_notice("Yanıt kopyalandı.")

    def tick(self):
        owner = self.runtime._p().slug
        if owner != self.owner:
            self.owner = owner
            self.generation += 1
            self.last_reply = self.active_rid = self.notice = self.badge = ""
            self.jobs = []
            self.files = []
            self.file_inflight = False
            self.selected_job = self.job_fingerprints = None
            self.jobs_inflight = self.pending = False
            self.clear_file()
            if self.panel is not None:
                self.entry.delete(0, "end")
                self.switch("reply")
                self.panel.withdraw()
            self.mascot.set_badge("")
        if time.monotonic() >= self.next_jobs:
            self.next_jobs = time.monotonic() + (3 if self.view in {"job", "jobs"} and self.panel is not None and self.panel.winfo_viewable() else 10)
            self._refresh_jobs()
        for _ in range(40):
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            self._event(message)
        for _ in range(20):
            try:
                item = self.local.get_nowait()
            except queue.Empty:
                break
            if item == "compose":
                self.mascot.show()
                self.open(focus=True)
                continue
            if item == "hotkey_registered":
                self.hotkey_registered = True
                continue
            if item == "hotkey_unavailable":
                self.hotkey_registered = False
                if not self.runtime._tray:
                    self.mascot.show()
                self._set_notice("Kısayol başka bir uygulamada kullanılıyor.")
                continue
            tag, owner, generation, callback, result, error = item
            if owner != self.owner or generation != self.generation:
                continue
            if tag in {"send", "control"}:
                self.pending = False
            if tag == "jobs":
                self.jobs_inflight = False
            if tag == "files":
                self.file_inflight = False
            if error:
                if tag == "send":
                    self.active_rid = ""
                self._set_notice(error)
            elif callback:
                callback(result)
        if self.panel is not None:
            if not self.notice and self.status.cget("text") != self._status_text():
                self.status.configure(text=self._status_text())
            self._update_actions()

    def _event(self, event):
        if event.get("user") != self.owner:
            return
        kind, value, rid = event.get("k"), str(event.get("t") or ""), event.get("rid")
        if kind == "user" and rid and event.get("x") == "ses":
            self.active_rid = rid
        if kind == "assistant" and value:
            self.last_reply = value
            if self.view == "reply" and self.panel is not None:
                self._render()
            self.badge = "Yanıt"
            if rid and rid == self.active_rid:
                self.active_rid = ""
            if not self.mascot._hidden and not self.runtime._main_window_open() and self.view == "reply":
                self.open()
            self._set_notice("")
        elif kind == "state" and value in STATUS:
            if rid == self.active_rid and value == "idle":
                self.active_rid = ""
            if not self.active_rid or (value != "idle" and (not rid or rid == self.active_rid)):
                self._set_notice("")
        elif kind == "step" and rid and rid == self.active_rid:
            self._set_notice(value[:100])
        elif kind == "reconcile":
            self._refresh_jobs()
        elif kind == "activity" and "|Hedef|" in str(event.get("x") or ""):
            self.next_jobs = min(self.next_jobs, time.monotonic() + 1)
        elif kind == "system" and value and self.panel is not None:
            self._set_notice(value[:120])
