"""Planlayıcı model yokken (Ollama/LM Studio kurulu değil, kota, ağ) genel hedeflerin modelsiz teslimi.

Haber hedefleri kendi kaynak kurtarmasını (news_recovery) kullanır; burası diğer bütün hedefler içindir.
Yeni araç çalıştırmaz, hedefi tamamlanmış saymaz, onay vermez: yalnız o ana kadar gerçekten
tamamlanmış ve yeniden doğrulanan adım çıktılarını kullanıcıya teslim eder, modelin neden
kullanılamadığını tek ve açık bir cümleyle söyler. Hedef açık kalır; model dönünce "hedef devam" sürdürür.
"""
import time

from modules import failure_policy, goal_tools

# Planlayıcının hiç yanıt veremediği sağlayıcı/ortam hataları (araç ya da doğrulama hatası değil).
MODEL_DOWN = {failure_policy.RATE_LIMIT, failure_policy.QUOTA_EXHAUSTED, failure_policy.LOCAL_MODEL,
              failure_policy.AUTH, failure_policy.DNS, failure_policy.NETWORK,
              failure_policy.TIMEOUT, failure_policy.PROVIDER_DOWN, failure_policy.PROVIDER_EXHAUSTED,
              failure_policy.ENVIRONMENT}


def model_down(exc):
    """Planlayıcı çağrısı modelin yokluğu yüzünden mi düştü?"""
    from modules import llm
    return isinstance(exc, llm.LocalModelError) or failure_policy.classify(exc) in MODEL_DOWN


def reason(exc):
    """Kullanıcıya gösterilecek güvenli neden; ham sağlayıcı metni, anahtar veya yol sızmaz."""
    from modules import llm
    category = failure_policy.classify(exc)
    if category in MODEL_DOWN - {failure_policy.ENVIRONMENT, failure_policy.LOCAL_MODEL}:
        return failure_policy.explain(exc)
    if isinstance(exc, llm.LocalModelError):
        text = str(exc)
        if llm.provider() == 'ollama' or any(name in text for name in llm.LOCAL_LABELS.values()):
            return 'Yerel model kullanılamıyor. ' + llm.local_hint()
        if 'anahtar' in text.casefold():
            return 'Bu kullanıcı için kullanılabilir model anahtarı yok; Yapay zekâ ayarlarından kendi anahtarını ekle.'
        return 'Seçili model sağlayıcısı yanıt vermedi.'
    return failure_policy.explain(exc)


def verified_outputs(job):
    """Tamamlanmış ve şu an yeniden doğrulanan adım kimlikleri (adım sırasıyla)."""
    ids = []
    for step in job.get('steps', []):
        ident = step.get('id') if isinstance(step, dict) else None
        output = job.get('outputs', {}).get(ident)
        if not ident or not isinstance(output, dict) or output.get('state') != 'done' or step.get('state') != 'done':
            continue
        try:
            goal_tools.verify(output, job['owner'])
        except (ValueError, PermissionError, OSError):
            continue
        ids.append(ident)
    return ids


def attach(job, exc):
    """Modelsiz teslimi işe yazar ve engel metnini günceller. Hedef durumu değişmez."""
    if job.get('state') in {'done', 'cancelled', 'approval', 'review', 'question'}:
        return
    evidence = verified_outputs(job)
    why = reason(exc)
    job['model_free'] = {'category': failure_policy.classify(exc), 'reason': why, 'evidence': evidence, 'at': time.time()}
    if evidence:
        job['blocker'] = (f'Planlayıcı model şu an kullanılamıyor. Modelsiz yol: doğrulanmış {len(evidence)} sonuç aşağıda '
                          'teslim edildi; kalan hedefler açık tutuldu. Model dönünce “hedef devam” de.\n' + why)
    else:
        job['blocker'] = ('Planlayıcı model şu an kullanılamıyor; henüz doğrulanmış bir sonuç yok. Hedef ve plan '
                          'korundu, model dönünce “hedef devam” de.\n' + why)


def render_lines(job, shown=()):
    """Teslim edilen doğrulanmış çıktıların sohbet satırları; render anında yeniden doğrulanır."""
    delivery = job.get('model_free')
    if not isinstance(delivery, dict) or job.get('state') in {'done', 'cancelled'}:
        return []
    lines = []
    steps = {s.get('id'): s for s in job.get('steps', []) if isinstance(s, dict)}
    for ident in delivery.get('evidence', []):
        if ident in shown:
            continue
        output = job.get('outputs', {}).get(ident)
        if not isinstance(output, dict):
            continue
        try:
            goal_tools.verify(output, job['owner'])
        except (ValueError, PermissionError, OSError):
            continue
        tool = steps.get(ident, {}).get('tool', 'araç')
        lines.append('Modelsiz teslim (doğrulandı) · ' + tool + ': ' + str(output.get('text', ''))[:1200])
        for item in output.get('files', []):
            lines.append('Dosya: ' + item['file'])
        if output.get('file') and not output.get('files'):
            lines.append('Dosya: ' + output['file'])
    return lines
