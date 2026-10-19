import re


def target_from_command(command: str) -> str:
    """Accept Turkish characters and fast keyboard spellings; exclude source -den/-dan."""
    normalized = command.casefold().translate(str.maketrans('çğıöşü', 'cgiosu')).replace('i\u0307', 'i')
    names = {'turkce': 'Türkçe', 'ingilizce': 'İngilizce', 'almanca': 'Almanca',
             'fransizca': 'Fransızca', 'arapca': 'Arapça', 'rusca': 'Rusça', 'ispanyolca': 'İspanyolca'}
    matches = re.findall(r"\b(turkce|ingilizce|almanca|fransizca|arapca|rusca|ispanyolca)(?:['’]?ye|['’]?ya)?\b(?!den|dan)", normalized)
    return names[matches[-1]] if matches else ''

