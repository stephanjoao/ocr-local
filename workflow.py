"""Fluxo persistente: leitura → respostas humanas → PDF.

A interface e o terminal usam as mesmas regras. A leitura nunca gera PDF.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
import uuid

import ocr
import ordering
from settings import BATCHES, read_prompt, validate_config
from studio import collect_questions, correct_occurrences, make_pdf

MANIFEST = 'lote.json'


def save_batch(batch):
    path = Path(batch['directory']) / MANIFEST
    lock_path = path.with_suffix('.saving.lock')
    try:
        lock = lock_path.open('x', encoding='utf-8')
    except FileExistsError as error:
        raise ValueError('Este lote está sendo salvo em outra sessão. Tente novamente.') from error
    try:
        with lock:
            revision = batch.get('revision', 0)
            if path.exists():
                current = json.loads(path.read_text(encoding='utf-8'))
                if current.get('revision', 0) != revision:
                    raise ValueError('Este lote foi alterado em outra sessão. Reabra o lote para continuar.')
            payload = {**batch, 'revision': revision + 1, 'updated_at': ocr.now()}
            ocr.write_json(path, payload)
            batch.update(payload)
    finally:
        lock_path.unlink(missing_ok=True)


def load_batch(directory):
    path = Path(directory)
    if path.is_dir():
        path /= MANIFEST
    batch = json.loads(path.read_text(encoding='utf-8'))
    if batch.get('schema_version') != 1:
        raise ValueError('Formato de lote incompatível.')
    batch['directory'] = str(path.resolve().parent)
    return batch


def list_batches(root=BATCHES):
    return sorted(Path(root).glob('*/' + MANIFEST), key=lambda p: p.stat().st_mtime, reverse=True)


def create_batch(files, config, root=BATCHES):
    """files é uma sequência de (nome, bytes), na ordem escolhida."""
    config = validate_config(config)
    files = list(files)
    if not files:
        raise ValueError('Envie pelo menos uma imagem ou PDF.')
    for name, data in files:
        if Path(name).suffix.lower() not in ocr.EXTENSIONS:
            raise ValueError(f'Formato não suportado: {name}')
        if not data:
            raise ValueError(f'Arquivo vazio: {name}')
    batch_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    directory = Path(root).resolve() / batch_id
    incoming = directory / 'originais'
    incoming.mkdir(parents=True)
    entries = []
    for index, (name, data) in enumerate(files, 1):
        name = Path(name.replace('\\', '/')).name
        safe = re.sub(r'[^\w. -]', '_', name)
        relative = f'{index:03}-{safe}'
        (incoming / relative).write_bytes(data)
        entries.append({'name': name, 'path': relative})
    batch = {
        'schema_version': 1, 'id': batch_id, 'directory': str(directory),
        'revision': 0, 'status': 'new', 'config': config, 'files': entries,
        'pages': [], 'recipes': [], 'questions': [], 'answers': {}, 'failures': [],
        'history': [], 'pdf': None, 'created_at': ocr.now(),
        'prompts': {'ocr': read_prompt('prompt.txt'), 'review': read_prompt('prompt_revisao.txt'),
                    'order': read_prompt('prompt_ordenacao.txt')},
        'organization': None,
    }
    save_batch(batch)
    return batch


@contextmanager
def processing_lock(directory):
    path = directory / '.processing.lock'
    try:
        with path.open('x', encoding='utf-8') as lock:
            lock.write(ocr.now())
    except FileExistsError as error:
        raise ValueError('Este lote já está sendo processado em outra sessão.') from error
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def analyze_batch(batch, progress=None):
    """Reusa OCR íntegro ao retomar; salva resultados após cada arquivo."""
    directory = Path(batch['directory'])
    output = directory / 'processamento'
    config = validate_config(batch['config'])
    notify = progress or (lambda fraction, title, detail: None)
    old_recipes = {recipe['id']: recipe for recipe in batch['recipes']}
    with processing_lock(directory):
        batch.update(status='reading', pdf=None, failures=[])
        save_batch(batch)
        try:
            notify(0, 'Preparando leitura', 'Verificando o modelo local…')
            model_digest = ocr.check_model(config)
            if batch.get('model_digest') not in (None, model_digest):
                raise ValueError('O modelo mudou desde a leitura. Crie um novo trabalho para preservar esta revisão.')
            batch['model_digest'] = model_digest
            counts = {}
            for entry in batch['files']:
                try:
                    counts[entry['path']] = ocr.page_count(directory / 'originais' / entry['path'])
                    if not counts[entry['path']]:
                        raise ValueError('Documento sem páginas.')
                except Exception as error:
                    batch['failures'].append(f"{entry['name']}: {error}")
            total = sum(counts.values())
            done = 0
            pages = []
            for entry in batch['files']:
                if entry['path'] not in counts:
                    continue
                def update(number, stage):
                    offset = {'Preparando página': 0, 'Lendo texto da imagem': .15,
                              'Revisando e filtrando receitas': .55, 'Página concluída': 1}.get(stage, 0)
                    notify(.9 * min((done + number - 1 + offset) / max(total, 1), 1), stage,
                           f"Página {done + number} de {total} · {entry['name']} · folha {number}")
                try:
                    records, _ = ocr.process_file(
                        directory / 'originais' / entry['path'], Path(entry['path']), output,
                        config, batch['prompts']['ocr'], model_digest,
                        review_prompt=batch['prompts']['review'], progress=update)
                    for record in records:
                        if record.get('review_status') in ('ok', 'skipped'):
                            page = json.loads(Path(record['editorial']).read_text(encoding='utf-8'))
                            page['preview'] = str((output / record['metadata']).with_suffix('.png'))
                            page['label'] = entry['name']
                            pages.append(page)
                        else:
                            batch['failures'].append(
                                f"{entry['name']}, folha {record['page']}: {record.get('error', record['status'])}")
                except Exception as error:
                    batch['failures'].append(f"{entry['name']}: {error}")
                done += counts[entry['path']]
                batch['pages'] = pages
                _assemble_review(batch, old_recipes)
                save_batch(batch)
            organize_batch(batch, progress=lambda i, total: notify(
                .9 + .09 * i / max(total, 1), 'Conectando e ordenando receitas',
                f'Comparação {i} de {total} · procurando continuações entre páginas'))
            batch['status'] = 'review'
            save_batch(batch)
            notify(1, 'Leitura concluída', 'Confira as dúvidas antes de gerar o PDF.')
        except BaseException:
            batch['status'] = 'interrupted'
            save_batch(batch)
            raise
    return batch


def _assemble_review(batch, old_recipes):
    recipes = []
    for page in batch['pages']:
        source = f"{page['source']} · página {page['page']}"
        for index, data in enumerate(page['data']['receitas']):
            recipe_id = ocr.digest(f'{source}:{index}'.encode())[:16]
            recipes.append(old_recipes.get(recipe_id, {
                **data, 'id': recipe_id, 'source': source, 'include': True,
                'warnings': list(page['data']['avisos']),
            }))
    batch['recipes'] = recipes
    batch['questions'] = collect_questions(batch['pages'])
    batch['answers'] = {q['id']: batch['answers'][q['id']] for q in batch['questions']
                        if q['id'] in batch['answers']}


def pending_questions(batch):
    return [q for q in batch['questions'] if q['id'] not in batch['answers']]


def organization_pending(batch):
    plan = batch.get('organization') or {}
    return len(batch['recipes']) > 1 and plan.get('status') not in ('unchanged', 'approved', 'kept')


def organize_batch(batch, progress=None, force=False):
    """Registra uma proposta; não altera os trechos nem gera o PDF."""
    recipes = batch['recipes']
    signature = ordering.fingerprint(recipes)
    current = batch.get('organization') or {}
    if not force and current.get('fingerprint') == signature and current.get('status') != 'error':
        return
    if not force and current.get('status') in ('approved', 'kept'):
        try:
            ordering.validate_groups(current['groups'], recipes)
            return  # Uma decisão humana continua válida para os mesmos trechos.
        except ValueError:
            pass
    prompt = batch['prompts'].setdefault('order', read_prompt('prompt_ordenacao.txt'))
    try:
        proposal = ordering.suggest(recipes, batch['config'], prompt, ocr.api_request, progress)
        ordering.validate_groups(proposal['groups'], recipes)
        proposal.update(status='unchanged' if proposal['groups'] == ordering.identity_groups(recipes) else 'pending',
                        fingerprint=signature)
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
        proposal = {'groups': ordering.identity_groups(recipes), 'links': [], 'status': 'error',
                    'error': str(error), 'fingerprint': signature}
    batch.update(organization=proposal, pdf=None,
                 status='reading' if batch['status'] == 'reading' else 'review')
    save_batch(batch)


def set_organization(batch, groups):
    ordering.validate_groups(groups, batch['recipes'])
    candidate = deepcopy(batch)
    candidate.update(organization={
        'groups': groups, 'links': [], 'status': 'pending', 'manual': True,
        'fingerprint': ordering.fingerprint(batch['recipes']),
    }, pdf=None, status='review')
    save_batch(candidate)
    batch.update(candidate)


def confirm_organization(batch, accept):
    candidate = deepcopy(batch)
    plan = candidate.get('organization') or {}
    if accept and plan.get('status') == 'error':
        raise ValueError('A análise da sequência falhou. Ajuste manualmente ou mantenha a ordem enviada.')
    groups = plan.get('groups') if accept else ordering.identity_groups(candidate['recipes'])
    ordering.validate_groups(groups, candidate['recipes'])
    candidate['organization'] = {**plan, 'groups': groups, 'status': 'approved' if accept else 'kept',
                                 'fingerprint': ordering.fingerprint(candidate['recipes'])}
    candidate['history'].append({'event': 'organization', 'accepted': accept, 'groups': deepcopy(groups), 'at': ocr.now()})
    candidate.update(pdf=None, status='review')
    save_batch(candidate)
    batch.update(candidate)


def answer_question(batch, question_id, action, original='', replacement='', note=''):
    question = next((q for q in batch['questions'] if q['id'] == question_id), None)
    if not question:
        raise ValueError('Dúvida não encontrada neste lote.')
    if action not in ('correct', 'keep', 'checked'):
        raise ValueError('Escolha como responder à dúvida.')
    candidate = deepcopy(batch)
    count = 0
    if action == 'correct':
        candidate['recipes'], count = correct_occurrences(candidate['recipes'], question, original, replacement)
    answer = {'action': action, 'original': original, 'replacement': replacement,
              'note': note.strip(), 'occurrences': count, 'answered_at': ocr.now()}
    candidate['answers'][question_id] = answer
    candidate['history'].append({'question_id': question_id, **answer})
    candidate.update(pdf=None, status='review')
    save_batch(candidate)
    batch.update(candidate)
    return count


def edit_recipe(batch, recipe_id, values):
    candidate = deepcopy(batch)
    recipe = next((r for r in candidate['recipes'] if r['id'] == recipe_id), None)
    if recipe is None:
        raise ValueError('Receita não encontrada.')
    if not values.get('titulo', '').strip():
        raise ValueError('Dê um título à receita.')
    for field in ('ingredientes', 'preparo', 'observacoes'):
        if not isinstance(values.get(field), list) or not all(isinstance(x, str) for x in values[field]):
            raise ValueError(f'Conteúdo inválido: {field}')
    before = deepcopy(recipe)
    recipe.update({key: values[key] for key in ('titulo', 'ingredientes', 'preparo', 'observacoes')})
    recipe['include'] = bool(values.get('include', True))
    candidate['history'].append({'recipe_id': recipe_id, 'before': before, 'after': deepcopy(recipe), 'at': ocr.now()})
    candidate.update(pdf=None, status='review')
    save_batch(candidate)
    batch.update(candidate)


def export_pdf(batch, confirmed=False, allow_partial=False):
    if batch['status'] not in ('review', 'ready'):
        raise ValueError('Conclua a leitura antes de gerar o PDF.')
    if pending_questions(batch):
        raise ValueError('Responda a todas as dúvidas antes de gerar o PDF.')
    if organization_pending(batch):
        raise ValueError('Confira a sequência e as continuações das receitas antes de gerar o PDF.')
    if not confirmed:
        raise ValueError('Confirme a conferência das receitas antes de gerar o PDF.')
    if batch['failures'] and not allow_partial:
        raise ValueError('Há páginas com falha. Autorize um PDF parcial ou retome a leitura.')
    groups = (batch.get('organization') or {}).get('groups', ordering.identity_groups(batch['recipes']))
    recipes = ordering.materialize(batch['recipes'], groups)
    for recipe in recipes:
        recipe['warnings'] = []
        for question in batch['questions']:
            answer = batch['answers'][question['id']]
            if answer['action'] == 'keep' and set(recipe['sources']).intersection(question['sources']):
                recipe['warnings'].append(question['text'])
        recipe['warnings'] = list(dict.fromkeys(recipe['warnings']))
    data = make_pdf(recipes)
    candidate = deepcopy(batch)
    directory = Path(candidate['directory'])
    name = f"receitas-v{candidate['revision'] + 1}-{uuid.uuid4().hex[:8]}.pdf"
    (directory / name).write_bytes(data)
    candidate.update(pdf=name, status='ready')
    candidate['history'].append({'event': 'pdf', 'file': name, 'partial': bool(batch['failures']), 'at': ocr.now()})
    try:
        save_batch(candidate)
    except Exception:
        (directory / name).unlink(missing_ok=True)
        raise
    batch.update(candidate)
    return directory / name
