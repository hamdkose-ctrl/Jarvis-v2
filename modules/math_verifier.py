"""Bounded exact arithmetic checks; never execute model code or infer unread text."""
import ast
from fractions import Fraction
import re


class Unsupported(ValueError):
    pass


class Undefined(Unsupported):
    pass


def normalize(text):
    if not isinstance(text, str) or len(text) > 600:
        raise Unsupported('İfade sınırı aşıldı.')
    text = text.strip().strip('$').replace('−', '-').replace('×', '*').replace('÷', '/')
    text = text.replace('²', '^2').replace('³', '^3')
    for command in ('\\left', '\\right', '\\,', '\\!'):
        text = text.replace(command, '')
    text = text.replace('\\cdot', '*').replace('\\times', '*').replace('\\div', '/')
    def group(pos):
        while pos < len(text) and text[pos].isspace(): pos += 1
        if pos >= len(text) or text[pos] != '{': raise Unsupported('Kesir biçimi desteklenmiyor.')
        depth, start = 1, pos + 1
        pos += 1
        while pos < len(text) and depth:
            depth += (text[pos] == '{') - (text[pos] == '}');pos += 1
        if depth: raise Unsupported('Kesir tamamlanmamış.')
        return text[start:pos-1], pos
    for _ in range(20):
        match = re.search(r'\\(?:dfrac|tfrac|frac)', text)
        if not match: break
        numerator, pos = group(match.end());denominator, end = group(pos)
        text = text[:match.start()] + '((' + numerator + ')/(' + denominator + '))' + text[end:]
    if '\\' in text: raise Unsupported('Bu matematik yazımı desteklenmiyor.')
    text = text.replace('{', '(').replace('}', ')').replace('^', '**')
    text = re.sub(r'(?<=\d),(?=\d)', '.', text)
    text = re.sub(r'(?<=\d)(?=[A-Za-z(])(?![eE][+-]?\d)|(?<=\))(?=[A-Za-z(\d])', '*', text)
    return text.strip()


def calculate(text, variables=None):
    source = normalize(text)
    try: tree = ast.parse(source, mode='eval')
    except SyntaxError as exc: raise Unsupported('İfade ayrıştırılamadı.') from exc
    if len(list(ast.walk(tree))) > 120: raise Unsupported('İfade çok uzun.')
    variables = variables or {}
    def visit(node, depth=0):
        if depth > 24: raise Unsupported('İfade çok derin.')
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            segment = ast.get_source_segment(source, node)
            if len(segment) > 80: raise Unsupported('Sayı çok uzun.')
            exponent = re.search(r'[eE]([+-]?\d+)$', segment)
            if exponent and (len(exponent[1].lstrip('+-')) > 3 or abs(int(exponent[1])) > 100):
                raise Unsupported('Bilimsel gösterim sınırı aşıldı.')
            value = Fraction(segment)
        elif isinstance(node, ast.Name) and node.id in variables:
            value = variables[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth+1) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            left, right = visit(node.left, depth+1), visit(node.right, depth+1)
            if isinstance(node.op, ast.Add): value = left + right
            elif isinstance(node.op, ast.Sub): value = left - right
            elif isinstance(node.op, ast.Mult): value = left * right
            elif isinstance(node.op, ast.Div): value = left / right
            else:
                if right.denominator != 1 or abs(right) > 100: raise Unsupported('Üs sınırı aşıldı.')
                value = left ** int(right)
        else: raise Unsupported('Yalnız sayılar ve verilen değişkenlerle temel aritmetik desteklenir.')
        if value.numerator.bit_length() > 4096 or value.denominator.bit_length() > 4096:
            raise Unsupported('Hesap boyutu sınırı aşıldı.')
        return value
    try: return visit(tree.body)
    except ZeroDivisionError as exc:
        raise Undefined('Sıfıra bölme tanımsızdır.') from exc
    except (ValueError, OverflowError) as exc:
        raise Unsupported('İfade tanımsız veya hesap kapsamı dışında.') from exc


def verify(work, text=''):
    variables = {}
    if work:
        for given in work.get('given', []):
            match = re.fullmatch(r'\s*([A-Za-z])\s*=\s*(.+)', given)
            if match:
                try: variables[match[1]] = calculate(match[2])
                except Unsupported: pass
    rows = []
    expressions = [step['expression'] for step in work.get('steps', [])] if work else []
    # Plain prose can still contain numeric equalities; do not guess symbolic prose.
    if not work:
        candidates = re.findall(r'\$([^$]+)\$', text) + re.split(r'[;\n]|\.(?:\s|$)', text)
        expressions = []
        for candidate in candidates:
            candidate = candidate.rsplit(':', 1)[-1].strip()
            if '=' in candidate and re.fullmatch(r'[\d()+*/^²³×÷−.,\s=-]+', candidate):
                if candidate not in expressions: expressions.append(candidate)
    expected = None
    if work and work.get('goal') == 'solve' and work.get('scope') == 'question':
        try: expected = calculate(work.get('problem', ''), variables)
        except Unsupported: pass
    for index, expression in enumerate(expressions):
        parts = expression.split('=')
        row = {'step': index+1, 'status': 'unverified', 'expression': expression}
        try:
            values = []
            undefined = False
            for part in parts:
                try: values.append(calculate(part, variables))
                except Undefined:
                    values.append(None);undefined = True
                except Unsupported: values.append(None)
            known = [(a, b) for a, b in zip(values, values[1:]) if a is not None and b is not None]
            if known:
                row['status'] = 'correct' if len(known) == len(parts)-1 and all(a == b for a, b in known) else 'unverified'
                wrong = next(((a, b) for a, b in known if a != b), None)
                if wrong:
                    row['status'] = 'incorrect';row['expected'] = str(wrong[0])
            if work and work['steps'][index]['kind'] == 'final' and expected is not None:
                if values[-1] is not None:
                    if values[-1] != expected or row['status'] == 'incorrect':
                        row['status'] = 'incorrect';row['expected'] = str(expected)
                    elif len(parts) == 1 or row['status'] == 'correct':
                        row['status'] = 'correct'
            if undefined and len(parts) > 1:
                row['status'] = 'incorrect';row['expected'] = 'Sıfıra bölme tanımsızdır.'
        except Unsupported: pass
        rows.append(row)
    return {'status': 'incorrect' if any(r['status'] == 'incorrect' for r in rows) else ('checked' if any(r['status'] == 'correct' for r in rows) else 'unverified'),
            'checked': sum(r['status'] == 'correct' for r in rows), 'unverified': sum(r['status'] == 'unverified' for r in rows), 'steps': rows}
