"""Typed executors for the user-profile and saved-macro capabilities.

This module deliberately receives an already validated plan.  It never reads a
raw utterance and therefore cannot become a second semantic authority.
"""
from __future__ import annotations


def user_manage(runtime, args: dict) -> str:
    operation = args["operation"]
    if operation == "list":
        names = runtime.list_users()
        return "Kayıtlı kullanıcılar: " + ", ".join(names) + "." if names else "Kayıtlı kullanıcı yok."
    if operation == "identify":
        return f"Şu an {runtime.profile.name} ile konuşuyorum."
    if operation == "create":
        name = args["name"]
        return runtime._switch_user(name, created=not runtime.Profile(name).exists)
    if operation == "switch":
        return runtime._switch_user(args["name"])
    if operation == "rename":
        old, new = args.get("old") or runtime.profile.name, args["name"]
        err = runtime.rename_user(old, new)
        if err:
            return err
        try:
            key = runtime._llm.user_key(runtime.slugify(old))
            if key:
                runtime._llm.set_user_key(runtime.slugify(new), key)
                runtime._llm.set_user_key(runtime.slugify(old), None)
        except Exception:
            runtime._record_failure("modules.user_command_domain:user_manage.rename")
        if old.casefold() == runtime.profile.name.casefold():
            runtime._profiles.pop(runtime.profile.slug, None)
            runtime.profile = runtime._get_profile(new)
            runtime._llm.set_user_context(runtime.profile.slug)
        return f"Tamam, {old} adını {new} yaptım."
    if operation == "delete":
        victim = args["name"]
        if victim.casefold() == runtime.profile.name.casefold():
            return "Aktif kullanıcıyı silemem; önce başka bir kullanıcıya geç."
        return runtime.delete_user(victim) or f"{victim} kullanıcısını sildim (yedeği 'silinenler' klasöründe)."
    if operation == "goals_list":
        goals = runtime.profile.data["goals"]
        return "Hedeflerin: " + "; ".join(goals) + "." if goals else "Henüz bir hedef eklemedin."
    if operation == "goals_clear":
        runtime.profile.clear_goals()
        return f"{runtime.profile.name} için hedefleri sildim."
    if operation == "goal_add":
        text = args["text"]
        runtime.profile.add_goal(text)
        return f"Tamam {runtime.profile.name}, hedefini kaydettim: {text}."
    if operation == "fact_add":
        text = args["text"]
        runtime.profile.add_fact(text)
        return f"Hafızama kaydettim: {text}"
    return "Kullanıcı işlemi Core tarafından doğrulanmadı."


def macro_teach(runtime, args: dict) -> str:
    trigger, actions = args["trigger"], args["actions"]
    runtime.profile.data.setdefault("macros", {})[runtime._macro_key(trigger)] = {
        "title": trigger, "actions": list(actions)}
    runtime.profile.save()
    return f"Kısayolu kaydettim: “{trigger}” dediğinde şunları yapacağım: " + ", ".join(actions) + "."


def macro_manage(runtime, args: dict) -> str:
    macros = runtime.profile.data.get("macros") or {}
    if args["operation"] == "list":
        if not macros:
            return 'Kayıtlı kısayolun yok. Örnek: “çalışma modu dersem chrome aç”.'
        return "Kısayolların: " + "; ".join(
            f"{value['title']} → {', '.join(value['actions'])}" for value in macros.values()) + "."
    key = runtime._macro_key(args["trigger"])
    if key not in macros:
        return "Böyle bir kısayolun yok."
    title = macros.pop(key)["title"]
    runtime.profile.save()
    return f"“{title}” kısayolunu sildim."
