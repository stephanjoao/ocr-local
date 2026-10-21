"""Comandos simples para ler, conferir e montar o caderno de receitas."""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import subprocess
import sys

from settings import BATCHES, ROOT, load_config


def parser():
    result = argparse.ArgumentParser(
        description='Caderno de receitas local. Sem comando, abre a interface.',
        epilog='Fluxo: caderno ler scans/ → caderno conferir → caderno pdf')
    commands = result.add_subparsers(dest='command')
    ui = commands.add_parser('abrir', help='Iniciar a interface no navegador')
    ui.add_argument('--porta', type=int, default=8501)
    commands.add_parser('verificar', help='Verificar configuração, Ollama e modelo')
    read = commands.add_parser('ler', help='Ler imagens/PDFs e preparar as dúvidas, sem gerar PDF')
    read.add_argument('arquivos', nargs='*', type=Path, help='Arquivos ou pastas; padrão: scans/')
    commands.add_parser('listar', help='Listar os trabalhos salvos')
    for name, description in (
        ('retomar', 'Retomar a leitura de um lote interrompido'),
        ('conferir', 'Responder às dúvidas no terminal'),
        ('pdf', 'Gerar PDF depois de responder às dúvidas'),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument('lote', nargs='?', help='ID ou pasta do lote; padrão: o mais recente')
        if name == 'pdf':
            command.add_argument('--confirmar', action='store_true', help='Confirmar que conferiu as receitas')
            command.add_argument('--parcial', action='store_true', help='Aceitar um PDF com páginas pendentes')
    return result


def resolve_batch(value, root=BATCHES):
    import workflow
    if value:
        path = Path(value)
        if not path.exists():
            path = Path(root) / value
    else:
        batches = workflow.list_batches(root)
        if not batches:
            raise ValueError('Nenhum trabalho salvo. Comece com: ./caderno ler scans/')
        path = batches[0]
    return workflow.load_batch(path)


def input_files(paths):
    import ocr
    result, seen = [], set()
    for path in paths or [ROOT / 'scans']:
        if not path.exists():
            raise ValueError(f'Arquivo ou pasta não encontrado: {path}')
        entries = sorted(path.rglob('*'), key=lambda p: p.as_posix().casefold()) if path.is_dir() else [path]
        for entry in entries:
            if entry.is_file() and not entry.is_symlink() and entry.suffix.lower() in ocr.EXTENSIONS:
                absolute = entry.resolve()
                if absolute not in seen:
                    result.append(absolute)
                    seen.add(absolute)
    if not result:
        raise ValueError('Nenhuma imagem ou PDF encontrado. Coloque os arquivos em scans/ ou informe seus caminhos.')
    return result


def show_progress(fraction, title, detail):
    print(f'[{fraction:4.0%}] {title} · {detail}', flush=True)


def summary(batch):
    import workflow
    print(f"\nLote: {batch['id']}")
    print(f"{len(batch['pages'])} página(s) lida(s), {len(batch['recipes'])} receita(s), "
          f"{len(workflow.pending_questions(batch))} dúvida(s) pendente(s).")
    for failure in batch['failures']:
        print(f'  Falha: {failure}')
    print(f"Salvo em: {batch['directory']}")
    if workflow.organization_pending(batch):
        print('Há uma sequência/continuação para conferir antes do PDF.')


def review_interactively(batch):
    import workflow
    if workflow.organization_pending(batch):
        plan = batch.get('organization') or {}
        recipes = {r['id']: r for r in batch['recipes']}
        print('\nSequência sugerida:')
        for i, group in enumerate(plan.get('groups', [[key] for key in recipes]), 1):
            print(f"{i}. " + ' → '.join(f"{recipes[key]['titulo']} ({recipes[key]['source']})" for key in group))
        for link in plan.get('links', []):
            print('  Motivo: ' + link['motivo'])
        if plan.get('error'):
            print('Análise incompleta: ' + plan['error'])
        while True:
            answer = input('[a] aceitar sequência, [m] manter ordem enviada e separar trechos, [s] sair: ').strip().lower()
            if answer == 's':
                return
            if answer not in ('a', 'm'):
                continue
            try:
                workflow.confirm_organization(batch, answer == 'a')
                break
            except ValueError as error:
                print(error)
    questions = workflow.pending_questions(batch)
    for index, question in enumerate(questions, 1):
        print(f"\nDúvida {index}/{len(questions)}: {question['text']}")
        print('Origem: ' + ' / '.join(question['sources']))
        for recipe in batch['recipes']:
            if recipe['source'] in question['sources']:
                print(f"\n  {recipe['titulo']}")
                for field in ('ingredientes', 'preparo', 'observacoes'):
                    for line in recipe[field]:
                        print(f'    {line}')
        while True:
            action = input('\n[c] corrigir, [m] manter com aviso, [v] conferi e está certo, [s] sair: ').strip().lower()
            if action == 's':
                return
            if action not in ('c', 'm', 'v'):
                print('Escolha c, m, v ou s.')
                continue
            original = replacement = ''
            if action == 'c':
                default = question.get('original', '')
                original = input(f'Trecho exato{f" [{default}]" if default else ""}: ').strip() or default
                replacement = input('Leitura correta: ').strip()
            try:
                workflow.answer_question(batch, question['id'], {'c': 'correct', 'm': 'keep', 'v': 'checked'}[action],
                                         original, replacement)
                print('Resposta salva.')
                break
            except ValueError as error:
                print(error)
    print('\nDúvidas respondidas. Confira as receitas na interface e gere com: ./caderno pdf')


def main(argv=None):
    args = parser().parse_args(argv)
    command = args.command or 'abrir'
    if command == 'abrir':
        port = getattr(args, 'porta', 8501)
        print(f'Interface: http://localhost:{port} · Ctrl+C encerra o servidor.', flush=True)
        env = os.environ.copy()
        # Ensure project root is in PYTHONPATH for workflow module to be found
        env['PYTHONPATH'] = f'{ROOT.absolute()}:{env.get("PYTHONPATH", "")}'
        return subprocess.call([
            sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'app_streamlit.py'),
            '--server.address', '127.0.0.1', '--server.port', str(port),
            '--server.headless', 'true',
        ], cwd=ROOT, env=env)
    import ocr
    import workflow
    if command == 'verificar':
        config = load_config()
        digest = ocr.check_model(config)
        print(f"Tudo pronto. Modelo: {config['model']} ({digest[:12]}).\nAbra a interface: ./caderno")
        return 0
    if command == 'listar':
        for manifest in workflow.list_batches():
            batch = workflow.load_batch(manifest)
            print(f"{batch['id']} · {batch['status']} · {len(batch['recipes'])} receitas")
        return 0
    if command == 'ler':
        paths = input_files(args.arquivos)
        batch = workflow.create_batch([(p.name, p.read_bytes()) for p in paths], load_config())
        workflow.analyze_batch(batch, show_progress)
        summary(batch)
        print('\nPróxima etapa: ./caderno conferir')
        return 1 if batch['failures'] else 0
    batch = resolve_batch(args.lote)
    if command == 'retomar':
        workflow.analyze_batch(batch, show_progress)
        summary(batch)
        return 1 if batch['failures'] else 0
    if command == 'conferir':
        if batch['status'] not in ('review', 'ready'):
            raise ValueError('Retome a leitura primeiro: ./caderno retomar')
        if not sys.stdin.isatty():
            raise ValueError('Abra um terminal interativo ou use a interface: ./caderno')
        review_interactively(batch)
        return 0
    if command == 'pdf':
        if workflow.pending_questions(batch) or workflow.organization_pending(batch):
            raise ValueError('Há dúvidas ou uma sequência pendentes. Execute: ./caderno conferir')
        confirmed = args.confirmar
        if not confirmed and sys.stdin.isatty():
            confirmed = input('Conferiu as receitas e deseja gerar o PDF? [s/N] ').strip().lower() == 's'
        path = workflow.export_pdf(batch, confirmed=confirmed, allow_partial=args.parcial)
        print(f'PDF pronto: {path}')
        return 0
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nInterrompido. Retome com: ./caderno retomar', file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Erro: {error}', file=sys.stderr)
        raise SystemExit(1)
