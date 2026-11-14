# Core capability / adapter envanteri — 14 Kasım 2026

Bu tablo main@7df1105 tabanındaki 68 kapalı Core capability için üretim map ve model argüman sözleşmesinden üretilmiştir. Kaynak sahibi `CORE_INTENTS`tir; yeni capability/izin kataloğu değildir. Tüm satırlar Core validator üzerinden mevcut domain işçisine gider. Schema olması canlı kabul veya dependency başarısı değildir.

`typed/mixed`: adapter doğrulanmış sonuç için ActionOutcome döndürebilir; pending ve doğrulanmamış alt işlemler yine ayrı değerlendirilir. `domain/unknown`: düz metin sonucu kendiliğinden success yapılmaz. Her iki grupta onay, izin ve gerçek hedef doğrulaması Core/domain sahibindedir.

| Capability | Core intent | Validator | Sonuç sınırı |
|---|---|---|---|
| `app.close` | `app_close` | `_app_close_args` | domain/unknown |
| `app.open` | `app_open` | `_app_open_args` | domain/unknown |
| `brief.read` | `daily_brief` | `_empty_action_args` | domain/unknown |
| `browser.page.read` | `browser_page` | `_browser_page_args` | domain/unknown |
| `calendar.read` | `agenda_read` | `_agenda_read_args` | domain/unknown |
| `contacts.manage` | `contacts_manage` | `_contacts_args` | domain/unknown |
| `conversation.table` | `conversation_table` | `_empty_action_args` | domain/unknown |
| `desktop.window.op` | `app_action` | `_window_op_args` | domain/unknown |
| `desktop.windows.list` | `app_action` | `_window_list_args` | domain/unknown |
| `development.manage` | `development_manage` | `_development_args` | domain/unknown |
| `device.share` | `share_control` | `_share_args` | domain/unknown |
| `documents.export` | `document_export` | `_empty_action_args` | domain/unknown |
| `files.folder_analyze` | `folder_analyze` | `_folder_analysis_args` | domain/unknown |
| `files.mutate` | `file_mutate` | `_file_mutate_args` | domain/unknown |
| `files.organize` | `file_organize` | `_organize_args` | domain/unknown |
| `files.read` | `file_action` | `_file_args` | domain/unknown |
| `filesend.transfer` | `filesend_transfer` | `_filesend_transfer_args` | domain/unknown |
| `finance.alert.manage` | `finance_alert_manage` | `_finance_alert_manage_args` | domain/unknown |
| `finance.read` | `finance_read` | `_finance_args` | domain/unknown |
| `git.publish` | `git_publish` | `_empty_action_args` | domain/unknown |
| `handoff.manage` | `handoff_manage` | `_handoff_manage_args` | domain/unknown |
| `hoca.lesson.start` | `hoca_start` | `_hoca_start_args` | domain/unknown |
| `jarvis.selfctl` | `selfctl` | `_selfctl_args` | domain/unknown |
| `kb.query` | `kb_query` | `_kb_query_args` | domain/unknown |
| `learning.manage` | `learning_manage` | `_learning_args` | domain/unknown |
| `macro.manage` | `macro_manage` | `_macro_manage_args` | domain/unknown |
| `macro.teach` | `macro_teach` | `_macro_teach_args` | domain/unknown |
| `mail.draft` | `outlook_draft` | `_outlook_draft_args` | domain/unknown |
| `mail.read` | `mail_read` | `_mail_read_args` | domain/unknown |
| `media.search` | `media_search` | `_media_search_args` | domain/unknown |
| `meeting.prepare` | `meeting_prepare` | `_meeting_prepare_args` | domain/unknown |
| `message.send` | `message_send` | `_message_args` | domain/unknown |
| `notes.add` | `notes_add` | `_note_add_args` | typed/mixed |
| `notes.manage` | `notes_manage` | `_notes_manage_args` | typed/mixed |
| `notes.read` | `notes_read` | `_notes_args` | typed/mixed |
| `notes.write` | `notes_write` | `_notes_write_args` | typed/mixed |
| `notify.manage` | `notify_manage` | `_notify_manage_args` | domain/unknown |
| `pc.audio.action` | `audio_action` | `_audio_args` | typed/mixed |
| `pc.guide.start` | `pc_guide_start` | `_pc_guide_start_args` | domain/unknown |
| `pc.level.set` | `level_set` | `_level_args` | typed/mixed |
| `pc.media.action` | `media_action` | `_media_args` | domain/unknown |
| `pc.shutdown.cancel` | `shutdown_cancel` | `_shutdown_args` | typed/mixed |
| `pc.shutdown.request` | `shutdown_request` | `_shutdown_args` | domain/unknown |
| `photo.action` | `photo_action` | `_photo_args` | domain/unknown |
| `reminder.propose` | `reminder` | `_reminder_args` | domain/unknown |
| `reminders.manage` | `reminder_manage` | `_reminder_manage_args` | domain/unknown |
| `research.search` | `task` | `_research_args` | domain/unknown |
| `screen.analyze` | `screen_analyze` | `_screen_args` | domain/unknown |
| `screen.capture` | `screen_capture` | `_capture_args` | domain/unknown |
| `screen.text` | `screen_text` | `_screen_text_args` | domain/unknown |
| `study.read` | `study_read` | `_study_read_args` | domain/unknown |
| `system.diagnose` | `system_diagnose` | `_empty_action_args` | domain/unknown |
| `system.update` | `system_update` | `_empty_action_args` | domain/unknown |
| `tasks.manage` | `tasks_manage` | `_tasks_manage_args` | typed/mixed |
| `text.translate` | `translate` | `_translate_args` | domain/unknown |
| `user.manage` | `user_manage` | `_user_manage_args` | domain/unknown |
| `visual.create` | `visual_create` | `_visual_args` | domain/unknown |
| `voice.rate` | `voice_rate` | `_voice_rate_args` | domain/unknown |
| `voice.select` | `voice_select` | `_voice_select_args` | domain/unknown |
| `voice.wake.enable` | `app_action` | `_wake_args` | domain/unknown |
| `watcher.manage` | `watcher_manage` | `_watcher_args` | domain/unknown |
| `weather.city.reset` | `city_reset` | `_city_reset_args` | typed/mixed |
| `weather.city.set` | `city_set` | `_city_set_args` | typed/mixed |
| `weather.read` | `weather` | `_weather_args` | domain/unknown |
| `weather.read.current` | `weather` | `_weather_args` | domain/unknown |
| `windows.settings.open` | `windows_settings_open` | `_windows_settings_args` | domain/unknown |
| `workbench.followup` | `workbench_followup` | `_workbench_followup_args` | domain/unknown |
| `worktrack.read` | `worktrack_read` | `_worktrack_read_args` | domain/unknown |
