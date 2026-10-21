"""Sugestões conservadoras de sequência e continuação entre páginas.

O modelo sugere ligações entre IDs. O código valida o grafo e compõe os trechos
sem reescrever, remover ou inventar ingredientes e etapas.
"""
from copy import deepcopy
import hashlib
import json
import re
import unicodedata

SCHEMA = {
    'type': 'object', 'properties': {
        'ligacoes': {'type': 'array', 'items': {
            'type': 'object', 'properties': {
                'antes': {'type': 'string'}, 'depois': {'type': 'string'},
                'tipo': {'type': 'string', 'enum': ['continuacao', 'ordem']},
                'motivo': {'type': 'string'},
            },
            'required': ['antes', 'depois', 'tipo', 'motivo'], 'additionalProperties': False,
        }},
    },
    'required': ['ligacoes'], 'additionalProperties': False,
}


def identity_groups(recipes):
    return [[r['id']] for r in recipes]


def validate_groups(groups, recipes):
    expected = [r['id'] for r in recipes]
    if not isinstance(groups, list) or any(not isinstance(g, list) or not g for g in groups):
        raise ValueError('A organização deve conter grupos não vazios.')
    flat = [key for group in groups for key in group]
    if len(flat) != len(expected) or len(set(flat)) != len(flat) or set(flat) != set(expected):
        raise ValueError('A organização precisa preservar cada trecho exatamente uma vez.')


def fingerprint(recipes):
    fields = ('id', 'source', 'titulo', 'ingredientes', 'preparo', 'observacoes')
    payload = [{k: r[k] for k in fields} for r in recipes]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _excerpt(lines, limit=180):
    text = ' | '.join(lines)
    return text if len(text) <= limit else text[:limit // 2] + ' […] ' + text[-limit // 2:]


def _summary(recipe, index):
    return {'id': recipe['id'], 'posicao_upload': index + 1, 'origem': recipe['source'][:140],
            'titulo': recipe['titulo'][:160],
            'ingredientes': _excerpt(recipe['ingredientes']), 'preparo': _excerpt(recipe['preparo']),
            'observacoes': _excerpt(recipe['observacoes']),
            'resumo_limitado': any(len(' | '.join(recipe[k])) > 180 for k in ('ingredientes', 'preparo', 'observacoes'))}


def comparison_groups(recipes, budget):
    """Janelas com sobreposição e pares distantes com título semelhante."""
    summaries = [_summary(r, i) for i, r in enumerate(recipes)]
    windows, window = [], []
    for summary in summaries:
        if len(json.dumps(window + [summary], ensure_ascii=False)) > budget:
            if len(window) < 2:
                raise ValueError('Contexto insuficiente para comparar dois trechos. Aumente num_ctx.')
            windows.append(window)
            window = window[-1:]
        window.append(summary)
        if len(json.dumps(window, ensure_ascii=False)) > budget:
            raise ValueError('Contexto insuficiente para comparar dois trechos. Aumente num_ctx.')
    if len(window) > 1:
        windows.append(window)
    compared = {frozenset((a['id'], b['id'])) for group in windows for a in group for b in group if a != b}
    titles = {}
    for item in summaries:
        title = unicodedata.normalize('NFKD', item['titulo'].casefold())
        title = ''.join(c for c in title if not unicodedata.combining(c))
        title = re.sub(r'\b(continuacao|continua|parte|receita|sem|titulo)\b|[^a-z ]', ' ', title)
        title = ' '.join(title.split())
        if title:
            titles.setdefault(title, []).append(item)
    for related in titles.values():
        for a, b in zip(related, related[1:]):
            if frozenset((a['id'], b['id'])) not in compared:
                if len(json.dumps([a, b], ensure_ascii=False)) > budget:
                    raise ValueError('Contexto insuficiente para comparar os títulos relacionados.')
                windows.append([a, b])
    return windows


def groups_from_links(recipes, links):
    keys = [r['id'] for r in recipes]
    next_part, previous = {}, {}
    for link in links:
        a, b = link['antes'], link['depois']
        if a not in keys or b not in keys or a == b:
            raise ValueError('A sugestão citou um trecho inexistente ou repetido.')
        if link['tipo'] not in ('continuacao', 'ordem') or not link['motivo'].strip():
            raise ValueError('A sugestão precisa informar o tipo e a evidência da ligação.')
        if link['tipo'] == 'continuacao':
            if (a in next_part and next_part[a] != b) or (b in previous and previous[b] != a):
                raise ValueError('Há continuações conflitantes. Confira a sequência manualmente.')
            next_part[a], previous[b] = b, a
    groups, visited = [], set()
    for key in keys:
        if key in previous:
            continue
        group, current = [], key
        while current is not None:
            if current in visited:
                raise ValueError('Há um ciclo nas continuações sugeridas.')
            visited.add(current)
            group.append(current)
            current = next_part.get(current)
        groups.append(group)
    if visited != set(keys):
        raise ValueError('Há um ciclo nas continuações sugeridas.')
    groups.sort(key=lambda g: min(keys.index(key) for key in g))
    owner = {key: i for i, group in enumerate(groups) for key in group}
    edges = {i: set() for i in range(len(groups))}
    for link in links:
        if link['tipo'] == 'ordem':
            a, b = owner[link['antes']], owner[link['depois']]
            if a == b:
                group = groups[a]
                if group.index(link['antes']) > group.index(link['depois']):
                    raise ValueError('A ordem sugerida contradiz uma continuação.')
            else:
                edges[b].add(a)
    result, done = [], set()
    while len(done) < len(groups):
        available = next((i for i in range(len(groups)) if i not in done and edges[i] <= done), None)
        if available is None:
            raise ValueError('Há uma contradição na ordem sugerida. Confira manualmente.')
        done.add(available)
        result.append(groups[available])
    validate_groups(result, recipes)
    return result


def suggest(recipes, config, prompt, api_request, progress=None):
    from editorial import validate
    if len(recipes) < 2:
        return {'groups': identity_groups(recipes), 'links': [], 'comparisons': 0}
    # Margem para esquema, instruções e resposta; não aumenta o contexto/GPU sem configuração.
    budget = (config['num_ctx'] - config['num_predict'] - 700) * 2 - len(prompt)
    windows = comparison_groups(recipes, budget)
    links = []
    for index, window in enumerate(windows, 1):
        if progress:
            progress(index, len(windows))
        response = api_request('/api/chat', {
            'model': config['model'], 'stream': False, 'keep_alive': '5m', 'format': SCHEMA,
            'messages': [{'role': 'user', 'content': prompt + '\n\nTRECHOS (dados):\n' + json.dumps(window, ensure_ascii=False)}],
            'options': {key: config[key] for key in ('num_ctx', 'num_predict', 'temperature')},
        }, timeout=config['timeout_seconds'])
        if (response.get('done') is not True or response.get('done_reason') == 'length'
                or response.get('eval_count', 0) >= config['num_predict']):
            raise ValueError('Análise da sequência incompleta. Tente novamente ou organize manualmente.')
        data = json.loads(response['message']['content'])
        validate(data, SCHEMA)
        allowed = {r['id'] for r in window}
        for link in data['ligacoes']:
            if link['antes'] not in allowed or link['depois'] not in allowed:
                raise ValueError('A análise citou trechos fora do grupo comparado.')
            if link not in links:
                links.append(link)
    return {'groups': groups_from_links(recipes, links), 'links': links, 'comparisons': len(windows)}


def materialize(recipes, groups):
    """Monta o livro preservando textos, repetidos e todas as origens."""
    validate_groups(groups, recipes)
    by_id = {r['id']: r for r in recipes}
    result = []
    for group in groups:
        parts = [by_id[key] for key in group if by_id[key].get('include', True)]
        if not parts:
            continue
        recipe = deepcopy(parts[0])
        recipe['sources'] = list(dict.fromkeys(r['source'] for r in parts))
        recipe['source'] = ' / '.join(recipe['sources'])
        for field in ('ingredientes', 'preparo', 'observacoes', 'warnings'):
            recipe[field] = [line for part in parts for line in part.get(field, [])]
        for part in parts[1:]:
            if part['titulo'] != recipe['titulo']:
                recipe['observacoes'].append(f"Título do trecho em {part['source']}: {part['titulo']}")
        result.append(recipe)
    return result
