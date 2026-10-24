# Yerel Git emniyet kemeri

Bu koruma GitHub branch protection/ruleset enforcement yerine geçmez. Private Free repo kısıtı nedeniyle sunucu tarafında enforce edilemeyen `main`/`master` doğrudan yazma kuralına, tek PC/tek kullanıcı düzeninde ek ve **atlanabilir** bir yerel güvenlik katmanı sağlar.

## Kapsam

- `.githooks/pre-commit`: aktif dal `main` veya `master` ise commit reddedilir.
- `.githooks/pre-push`: `refs/heads/main` veya `refs/heads/master` hedefine doğrudan push reddedilir.
- Mevcut başka bir remote branch'i geriye taşıyan non-fast-forward push reddedilir.
- `gpt/*` branch adı zorunlu değildir; bakım/hotfix branchleri serbesttir.
- Tam `modules.validation` push hook'una bağlanmaz. Resmî test kapısı Windows CI, gerçek PC kabulü watcher olarak kalır.
- Main değişimini ayrıca PC watcher izlemez; PR ilişkisi alarmı için `Main bekçisi` tek kaynak olarak kalır.

## Kurulum

Windows'ta repo kökünden:

```bat
scripts\git_hooks_kur.bat
```

veya:

```bat
py -3.13 -X utf8 scripts\install_git_hooks.py
```

Kurulum yalnız bu repo için şunu ayarlar:

```text
git config --local core.hooksPath .githooks
```

Global Git ayarı değiştirilmez.

## Bilinen sınırlar

- `git commit --no-verify` yerel `pre-commit` hook'unu atlayabilir.
- Başka makine, başka clone veya doğrudan GitHub API/server push bu yerel hook'lardan geçmez.
- Git `pre-push` hook'u komut satırındaki literal `--force` bayrağını almaz. Koruma, tehlikeli sonucu olan non-fast-forward ref güncellemesini tespit edip reddeder.
- Bu nedenle bu katmanın adı ve rolü **emniyet kemeri**dir; GitHub sunucu tarafı enforcement eşdeğeri değildir.
