"""Canonical Brain entry for Live tool commands.

Live keeps its voice-specific presentation here, but semantic understanding and
Core handoff use the same brain_entry contract as text/web/phone.
"""
from __future__ import annotations


def _live_command(runtime, text: str, *, _pre_registered_rid: str | None = None,
                  _pre_registered_owner: str | None = None) -> str:
    previous = (runtime._cur_source, runtime._cur_rid)
    owner = _pre_registered_owner or runtime.slugify(runtime.pc_profile().name)
    rid = _pre_registered_rid or runtime.secrets.token_hex(16)
    runtime._cur_source = "ses"
    runtime._cur_rid = rid
    try:
        if _pre_registered_rid is None and not runtime.requests_state.register(owner, rid):
            return "İstek kabul edilmedi; yeniden söyle."
        with runtime.requests_state.activate(owner, rid, foreground=True):
            from modules import brain_entry, core_brain_adapter

            runtime.log.info("İşlem kaydı: %s", "main.py:_live_command")
            runtime.emit("activity", "Komut motoru isteği işliyor", f"working|Komut motoru|{text[:220]}")
            runtime._session().speech_override = None
            entry = brain_entry.prepare(
                runtime, owner=owner, request_id=rid, text=text, source="ses",
                model_understanding=True,
            )
            from modules import brain_echo
            brain_echo.present(runtime, entry)
            try:
                runtime.requests_state.check()
                out, brain_feedback, brain_job_id = core_brain_adapter.handoff(runtime, entry, runtime.handle, text)
                runtime.log.info(
                    "Brain handoff: rid=%s stage=%s job=%s feedback=%s",
                    rid, entry.stage, brain_job_id or "-", brain_feedback.result_status,
                )
                runtime.requests_state.check()
            except runtime.requests_state.Cancelled:
                raise
            except (FileNotFoundError, ValueError) as exc:
                out = str(exc)
            except Exception as exc:
                runtime._record_failure("main.py:_live_command")
                try:
                    from modules import brain_failure_synthesis
                    feedback = brain_entry.last_feedback()
                    if feedback is not None and feedback.request_id == rid:
                        out = brain_failure_synthesis.synthesize(feedback, exc)
                    else:
                        from modules import diagnose
                        out = diagnose.explain(exc)
                except Exception:
                    runtime._record_failure("main.py:_live_command")
                    out = "Şu anda yapamadım, biraz sonra tekrar dener misin?"

            runtime.requests_state.check()
            if runtime._session().speech_override:
                spoken = runtime._session().speech_override
                runtime._session().speech_override = None
                runtime.emit("assistant", str(out), "ses")
                return spoken
            runtime._session().speech_override = None
            try:
                runtime.profile.log_agent(runtime.agents.classify(runtime._tr_lower(text)))
            except Exception:
                runtime._record_failure("main.py:_live_command")
            out = runtime._finalize(str(out).strip() if out else "Bir yanıt alamadım.")
            runtime.requests_state.check()
            runtime.emit("activity", "Komut motoru işlemi tamamladı", f"done|Komut motoru|{out[:420]}")
            if len(out) > 300:
                runtime.emit("assistant", out, "ses")
                if runtime._session().last_doc is not None and out.startswith(runtime._session().last_doc[0][:50]):
                    return (f"[Sonucun tamamı ekranda gösterildi. Bunu sesli okuma; kullanıcıya yalnızca şunu "
                            f"'{runtime._doc_ready_line(runtime._session().last_doc[2], out)}' de.]\n\n" + out[:1500])
            return out
    except runtime.requests_state.Cancelled as exc:
        runtime._session().speech_override = None
        return str(exc)
    finally:
        runtime._cur_source, runtime._cur_rid = previous
