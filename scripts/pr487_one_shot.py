from pathlib import Path

roadmap = Path('docs/Jarvis_Yol_Haritasi.md')
text = roadmap.read_text(encoding='utf-8')
lines = text.splitlines()
prefix = '- 🟡 (#477 + #486 / PR7 Closeout-B3c-3)'
new_line = ('- 🟡 (#477 + #486 + #487 / PR7 Closeout-B3c-3) `[1✓ 2🔄 3✓ 4✗]` '
            '`notes.read` Core yolu artık çıplak veri isteklerinde `göster/oku/say/listele` fiillerini kapsar; '
            '#486 `selfctl` UI navigation gölgesini kapattı. #487 named tek-not mutation hedefini Candidate Builder + '
            'Reference Resolver stable-ID referansından önerir ve ayrı `notes.write` Core doğrulamasına taşır; '
            'belirsiz/çözülemeyen hedef fail-closed netleştirme ister. `2. notu sil`, `tüm notları sil` ve not ekleme '
            'gibi bounded/domain protokolleri yeniden sınıflandırılmaz. #487 exact-head Windows CI + gerçek PC watcher '
            'PASS olmadan bu madde tamamlandı sayılmaz.')
idx = [i for i, line in enumerate(lines) if line.startswith(prefix)]
if idx != [idx[0]] if idx else True:
    raise SystemExit(f'roadmap notes line unique değil: {idx}')
lines[idx[0]] = new_line
roadmap.write_text('\n'.join(lines) + ('\n' if text.endswith('\n') else ''), encoding='utf-8')

test = Path('tests/test_brain_b3c3.py')
t = test.read_text(encoding='utf-8')
old = 'for text in ("notlarımı özetle", "notlarımı göster ve sil", "notlarımı listele"):'
new = 'for text in ("notlarımı özetle", "notlarımı göster ve sil"):'
if t.count(old) != 1:
    raise SystemExit('B3c3 stale expectation bulunamadı/çoğul')
t = t.replace(old, new)
old_plural = 'for text in ("notlarımı göster", "notları göster"):'
new_plural = 'for text in ("notlarımı göster", "notları göster", "notlarımı oku", "notlarımı say", "notları listele"):'
if t.count(old_plural) != 1:
    raise SystemExit('B3c3 plural read loop bulunamadı/çoğul')
t = t.replace(old_plural, new_plural)
test.write_text(t, encoding='utf-8')

# One-shot files must not survive in the final PR diff.
Path('.github/workflows/pr487-one-shot.yml').unlink(missing_ok=True)
Path('scripts/pr487_one_shot.py').unlink(missing_ok=True)
