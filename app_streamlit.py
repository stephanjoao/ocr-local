"""Interface do Caderno. As regras do fluxo vivem em workflow.py."""
from pathlib import Path
from io import BytesIO

import pypdfium2 as pdfium
import streamlit as st

from settings import ROOT, load_config
import workflow
import ordering


@st.cache_data(show_spinner=False)
def pdf_preview(data, number):
    with pdfium.PdfDocument(data) as document:
        page = document[number]
        try:
            bitmap = page.render(scale=1.4)
            try:
                image = bitmap.to_pil()
                buffer = BytesIO()
                image.save(buffer, format='PNG')
                return buffer.getvalue(), len(document)
            finally:
                bitmap.close()
        finally:
            page.close()


def activate(batch):
    st.session_state['active_batch'] = batch
    st.session_state.pop('flash', None)


def refresh(message=None):
    if message:
        st.session_state['flash'] = message
    st.rerun()


def render_progress(batch):
    pending = len(workflow.pending_questions(batch)) if batch else 0
    total = len(batch['questions']) if batch else 0
    ready = bool(batch and batch.get('pdf'))
    stage = 3 if ready else (2 if batch and batch['status'] == 'review' else 1)
    labels = ('Enviar e ler', 'Responder dúvidas', 'Gerar PDF')
    with st.container(border=True, key='workflow_progress'):
        steps = ''.join(f'<div class="workflow-step {"active" if i == stage else ""}">'
                        f'<span class="number">{i:02}</span>{label}</div>'
                        for i, label in enumerate(labels, 1))
        st.markdown(f'<div class="workflow">{steps}</div>', unsafe_allow_html=True)
        title = st.empty()
        detail = st.empty()
        bar = st.progress(0)
        if ready:
            title.write('**Seu PDF está pronto**')
            detail.caption('Você pode visualizar as páginas e baixar o livro à direita.')
            bar.progress(1.0)
        elif batch and batch['status'] == 'review':
            title.write('**Confira as receitas antes de gerar o PDF**')
            sequence = 'sequência para conferir' if workflow.organization_pending(batch) else 'sequência pronta'
            detail.caption(f'{total - pending} de {total} dúvidas respondidas · {sequence}')
            bar.progress(.65 + .2 * ((total - pending) / total if total else 1))
        elif batch and batch['status'] in ('interrupted', 'reading'):
            title.write('**A leitura precisa ser retomada**')
            detail.caption('As páginas já concluídas estão salvas neste lote.')
            bar.progress(.1)
        else:
            title.write('**Comece pelas páginas do seu caderno**')
            detail.caption('Envie os arquivos à esquerda. O PDF só será gerado depois da sua conferência.')
        def update(fraction, message, description):
            title.write('**' + message + '**')
            detail.caption(description)
            bar.progress(min(.65 * fraction, .65))
        return update


def render_history(batch):
    with st.expander('Trabalhos salvos'):
        manifests = workflow.list_batches()
        if not manifests:
            st.caption('Os trabalhos serão salvos automaticamente neste computador.')
        else:
            selected = st.selectbox('Escolha um trabalho', manifests,
                                    format_func=lambda p: p.parent.name, key='saved_batch')
            if st.button('Abrir trabalho', use_container_width=True):
                try:
                    activate(workflow.load_batch(selected))
                    st.rerun()
                except (OSError, ValueError, KeyError) as error:
                    st.error(f'Não foi possível abrir o trabalho: {error}')
        if batch:
            st.caption(f'Lote atual: {batch["id"]}')


def render_upload(batch, update):
    expanded = batch is None
    with st.expander('Enviar páginas' if batch else '1. Envie suas páginas', expanded=expanded):
        uploads = st.file_uploader('Imagens ou PDFs', accept_multiple_files=True,
                                  type=['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'pdf'],
                                  help='Selecione vários arquivos. A ordem da seleção será a ordem de leitura.')
        st.caption('JPG, PNG, WebP, TIFF ou PDF · várias páginas de uma vez')
        config = load_config()
        with st.expander('Modelo local'):
            config['model'] = st.text_input('Modelo do Ollama', config['model'])
        if uploads:
            st.caption(f'{len(uploads)} arquivo(s) selecionado(s). Um novo lote preserva os trabalhos anteriores.')
        if st.button('Ler páginas' if batch is None else 'Ler como novo trabalho', type='primary',
                     disabled=not uploads, use_container_width=True):
            try:
                current = workflow.create_batch([(u.name, u.getvalue()) for u in uploads], config)
                activate(current)
                with st.spinner('Lendo o caderno. O andamento aparece acima…'):
                    workflow.analyze_batch(current, update)
                refresh('Leitura concluída. Responda às dúvidas para continuar.')
            except Exception as error:
                st.error(f'Não foi possível concluir a leitura: {error}')
                st.caption('Use Retomar leitura para aproveitar as páginas que já foram salvas.')
    if batch and (batch['status'] in ('interrupted', 'reading', 'new') or batch['failures']):
        if st.button('Retomar leitura', use_container_width=True):
            try:
                with st.spinner('Retomando páginas pendentes…'):
                    workflow.analyze_batch(batch, update)
                refresh('Leitura retomada.')
            except Exception as error:
                st.error(str(error))


def render_questions(batch):
    questions = batch['questions']
    pending = workflow.pending_questions(batch)
    st.subheader('Dúvidas para conferir')
    if not questions:
        st.info('O modelo não sinalizou dúvidas. Confira as receitas antes de gerar o PDF.')
        return None
    st.caption(f'{len(pending)} pendente(s) de {len(questions)} · perguntas repetidas agrupadas por ocorrência')
    container = st.expander('Consultar ou alterar respostas') if not pending else st.container()
    if not pending:
        st.success('Respostas salvas com este PDF.' if batch.get('pdf') else
                   'Todas as dúvidas respondidas. Você já pode gerar o PDF.')
    with container:
        ordered = pending + [q for q in questions if q not in pending]
        ids = [q['id'] for q in ordered]
        by_id = {q['id']: q for q in ordered}
        selected = st.selectbox('Escolha uma dúvida', ids,
                                format_func=lambda key: ('✓ ' if key in batch['answers'] else '') + by_id[key]['text'],
                                key=f"question_{batch['id']}_{batch['revision']}")
        question = by_id[selected]
        render_question_editor(batch, question)
    return question['sources'][0] if question['sources'] else None


def render_question_editor(batch, question):
    selected = question['id']
    answer = batch['answers'].get(selected)
    with st.container(border=True):
        st.write('**' + question['text'].replace('*', '') + '**')
        st.caption('Aparece em: ' + ' / '.join(question['sources']))
        if answer:
            action_names = {'correct': 'Trecho corrigido', 'keep': 'Mantido com aviso', 'checked': 'Conferido'}
            st.success(action_names[answer['action']])
        action = st.radio('Como você quer tratar este ponto?', ['correct', 'keep', 'checked'],
                          index=None, key=f"action_{batch['id']}_{selected}_{batch['revision']}",
                          format_func=lambda value: {
                              'correct': 'Corrigir a leitura',
                              'keep': 'Não sei — manter o trecho e o aviso no PDF',
                              'checked': 'Conferi o original — o texto está certo',
                          }[value])
        with st.form(f"answer_{batch['id']}_{selected}_{batch['revision']}_{action}", border=False):
            original = replacement = ''
            if action == 'correct':
                original = st.text_input('Trecho a substituir', value=question.get('original', ''),
                                         help='Copie o trecho exato da receita.')
                replacement = st.text_input('Leitura correta', help='A correção vale para as ocorrências nas páginas indicadas.')
            with st.expander('Adicionar anotação'):
                note = st.text_input('Anotação da conferência (opcional)', help='Fica no histórico do trabalho.')
            if st.form_submit_button('Salvar resposta', type='primary', use_container_width=True, disabled=action is None):
                try:
                    workflow.answer_question(batch, selected, action, original, replacement, note)
                    refresh('Resposta salva. O PDF será gerado quando você concluir a conferência.')
                except (ValueError, OSError) as error:
                    st.error(str(error))


def render_recipes(batch):
    st.subheader('Receitas do livro')
    if not batch['recipes']:
        st.info('Nenhuma receita identificada. Consulte as páginas e o conteúdo separado.')
        return
    recipes = {r['id']: r for r in batch['recipes']}
    selected = st.selectbox('Escolha uma receita', list(recipes),
                            format_func=lambda key: recipes[key]['titulo'], key=f"recipe_{batch['id']}")
    recipe = recipes[selected]
    st.caption(recipe['source'])
    with st.form(f"edit_{batch['id']}_{selected}_{batch['revision']}", border=False):
        title = st.text_input('Título', recipe['titulo'])
        values = {'titulo': title}
        for field, label in (('ingredientes', 'Ingredientes · um por linha'),
                             ('preparo', 'Preparo · uma etapa por linha'), ('observacoes', 'Observações')):
            text = st.text_area(label, '\n'.join(recipe[field]), height=130 if field != 'observacoes' else 80)
            values[field] = [line.strip() for line in text.splitlines() if line.strip()]
        values['include'] = st.checkbox('Incluir esta receita no PDF', value=recipe.get('include', True))
        if st.form_submit_button('Salvar receita', use_container_width=True):
            try:
                workflow.edit_recipe(batch, selected, values)
                refresh('Receita salva. Gere o PDF quando terminar a conferência.')
            except (ValueError, OSError) as error:
                st.error(str(error))
    st.caption('Salve suas alterações antes de trocar de receita ou responder outra dúvida.')


def render_organization(batch):
    st.subheader('Sequência das receitas')
    st.caption('A ordem enviada é o ponto de partida. Continuações só são unidas depois da sua confirmação.')
    plan = batch.get('organization') or {}
    recipes = {r['id']: r for r in batch['recipes']}
    if not recipes:
        st.info('Não há receitas para ordenar.')
        return None
    if not plan:
        st.info('Este trabalho ainda não passou pela análise de sequência.')
    elif plan['status'] == 'error':
        st.warning('Não foi possível concluir a análise. Você pode ajustar a sequência ou manter a ordem enviada.')
        with st.expander('Detalhes da análise'):
            st.text(plan.get('error', 'Análise incompleta.'))
    elif plan['status'] == 'pending':
        st.info('Confira esta sequência antes de gerar o livro. Os textos dos trechos serão preservados.')
    elif plan['status'] == 'unchanged':
        st.info('Nenhuma mudança sustentada foi identificada. A ordem enviada foi mantida.')
    else:
        st.success('Sequência confirmada para o livro.')
    groups = plan.get('groups', ordering.identity_groups(batch['recipes']))
    with st.expander('Ver sequência do livro', expanded=plan.get('status') == 'pending'):
        for index, group in enumerate(groups, 1):
            st.write(f"**{index}. {recipes[group[0]]['titulo']}**")
            for part in group:
                st.caption(f"{recipes[part]['titulo']} · {recipes[part]['source']}")
            if len(group) > 1:
                st.caption(f'{len(group)} trechos na mesma receita, na ordem acima.')
        for link in plan.get('links', []):
            st.write(link['motivo'])
        if plan.get('comparisons', 0) > 1:
            st.caption('A comparação usou grupos sobrepostos e títulos relacionados. Trechos sem título muito afastados podem exigir ajuste manual.')
    if plan.get('status') == 'pending':
        if st.button('Usar esta sequência', type='primary', use_container_width=True):
            workflow.confirm_organization(batch, True)
            refresh('Sequência confirmada. Confira as dúvidas antes de gerar o PDF.')
    if plan.get('status') != 'kept':
        if st.button('Manter ordem enviada e trechos separados', use_container_width=True):
            workflow.confirm_organization(batch, False)
            refresh('Ordem enviada preservada.')
    with st.expander('Ajustar a sequência'):
        with st.form(f"move_{batch['id']}_{batch['revision']}", border=False):
            selected = st.selectbox('Receita a mover', range(len(groups)),
                                    format_func=lambda i: f"{i + 1}. {recipes[groups[i][0]]['titulo']}")
            position = st.number_input('Nova posição', min_value=1, max_value=len(groups), value=1, step=1)
            if st.form_submit_button('Mover receita', use_container_width=True):
                changed = [list(g) for g in groups]
                changed.insert(position - 1, changed.pop(selected))
                workflow.set_organization(batch, changed)
                refresh('Ordem ajustada. Confirme a sequência para continuar.')
        with st.form(f"join_{batch['id']}_{batch['revision']}", border=False):
            selected_parts = st.multiselect('Trechos da mesma receita, na ordem correta', list(recipes),
                                            format_func=lambda key: f"{recipes[key]['titulo']} · {recipes[key]['source']}")
            st.caption('Selecione primeiro o início, depois as continuações. Nenhum texto será apagado.')
            if st.form_submit_button('Unir estes trechos', use_container_width=True):
                if len(selected_parts) < 2:
                    st.error('Selecione pelo menos dois trechos.')
                else:
                    chosen = set(selected_parts)
                    changed, inserted = [], False
                    for group in groups:
                        if chosen.intersection(group) and not inserted:
                            changed.append(selected_parts)
                            inserted = True
                        remaining = [key for key in group if key not in chosen]
                        if remaining:
                            changed.append(remaining)
                    workflow.set_organization(batch, changed)
                    refresh('Junção preparada. Confirme a sequência para continuar.')
    if st.button('Analisar sequência' if not plan else 'Reavaliar sequência', use_container_width=True):
        with st.spinner('Procurando continuações entre páginas…'):
            workflow.organize_batch(batch, force=True)
        refresh('Análise da sequência atualizada.')
    return recipes[groups[0][0]]['source'] if groups else None


def render_notes(batch):
    with st.expander('Conteúdo separado das receitas'):
        found = False
        for page in batch['pages']:
            if page['data']['notas_pagina']:
                found = True
                st.caption(f"{page.get('label', page['source'])} · folha {page['page']}")
                st.text('\n\n'.join(page['data']['notas_pagina']))
        if not found:
            st.caption('Nenhum conteúdo separado neste lote.')


def render_export(batch):
    if batch.get('pdf'):
        st.caption('Para preparar outra versão, edite uma receita ou altere uma resposta.')
        return
    pending = workflow.pending_questions(batch)
    sequence_pending = workflow.organization_pending(batch)
    groups = (batch.get('organization') or {}).get('groups', ordering.identity_groups(batch['recipes']))
    included = len(ordering.materialize(batch['recipes'], groups))
    with st.container(border=True):
        st.subheader('Concluir e gerar PDF')
        if pending:
            st.caption(f'Falta responder {len(pending)} dúvida(s). Você pode manter uma incerteza com aviso.')
        if sequence_pending:
            st.caption('Confira também a ordem e as continuações em Sequência.')
        if not pending and not sequence_pending:
            st.caption(f'{included} receita(s) selecionada(s). Cada receita começa em uma página nova.')
        if batch['failures']:
            st.warning(f'{len(batch["failures"])} falha(s) na leitura. O livro ficará incompleto.')
            with st.expander('Ver falhas'):
                for failure in batch['failures']:
                    st.text(failure)
        with st.form(f"export_{batch['id']}_{batch['revision']}", border=False):
            confirmed = st.checkbox('Conferi as receitas e quero gerar o PDF')
            partial = st.checkbox('Gerar somente com as páginas lidas com sucesso') if batch['failures'] else False
            if st.form_submit_button('Gerar PDF', type='primary', use_container_width=True,
                                     disabled=bool(pending) or sequence_pending or not included):
                try:
                    with st.spinner('Montando o PDF…'):
                        workflow.export_pdf(batch, confirmed=confirmed, allow_partial=partial)
                    refresh('PDF gerado com suas respostas e correções.')
                except (ValueError, OSError) as error:
                    st.error(str(error))


def render_preview(batch, preferred_source=None):
    st.subheader('Seu caderno')
    if not batch or not batch['pages']:
        st.markdown('''<div class="empty-preview"><span style="font-size:2.5rem">▤</span>
        <strong>Das páginas ao livro</strong><p>Os originais aparecem aqui durante a conferência.
        Depois das suas respostas, este espaço mostra o PDF pronto.</p></div>''', unsafe_allow_html=True)
        return
    pdf_path = Path(batch['directory']) / batch['pdf'] if batch.get('pdf') else None
    view = 'Originais'
    if pdf_path:
        view = st.radio('Visualizar', ['PDF final', 'Originais'], horizontal=True, label_visibility='collapsed')
    if view == 'PDF final':
        try:
            data = pdf_path.read_bytes()
            st.download_button('Baixar livro em PDF', data, 'caderno-de-receitas.pdf', 'application/pdf',
                               use_container_width=True)
            _, total = pdf_preview(data, 0)
            number = st.selectbox('Página do PDF', range(total), format_func=lambda n: f'Página {n + 1} de {total}',
                                  key=f"pdf_page_{batch['id']}_{batch['pdf']}")
            preview, _ = pdf_preview(data, number)
            st.image(preview, width='stretch')
            st.caption('Receitas longas continuam na página seguinte, sem cortar texto.')
        except (OSError, ValueError, pdfium.PdfiumError) as error:
            st.error(f'Não foi possível abrir a prévia: {error}')
    else:
        sources = [f"{p['source']} · página {p['page']}" for p in batch['pages']]
        default = sources.index(preferred_source) if preferred_source in sources else 0
        page_index = st.selectbox('Página original', range(len(sources)), index=default,
                                  format_func=lambda n: f"{batch['pages'][n].get('label', batch['pages'][n]['source'])} · folha {batch['pages'][n]['page']}",
                                  key=f"original_{batch['id']}_{preferred_source}")
        page = batch['pages'][page_index]
        if Path(page['preview']).exists():
            st.image(page['preview'], width='stretch')
        else:
            st.info('A imagem desta página não está disponível neste computador.')
        st.caption('Compare esta página com as dúvidas à esquerda. O PDF ainda depende da sua conferência.'
                   if not pdf_path else 'Original preservado para consulta.')


def main():
    st.set_page_config(page_title='Caderno de receitas', page_icon='📖', layout='wide',
                       initial_sidebar_state='collapsed')
    st.markdown('<style>' + (ROOT / 'assets/interface.css').read_text() + '</style>', unsafe_allow_html=True)
    st.caption('CADERNO · RECEITAS')
    st.title('Seu caderno, página por página.')
    st.caption('Envie, confira as dúvidas e transforme suas receitas em um PDF.')
    batch = st.session_state.get('active_batch')
    update = render_progress(batch)
    if st.session_state.get('flash'):
        st.success(st.session_state.pop('flash'))
    left, right = st.columns(2, gap='large')
    preferred = None
    with left:
        render_upload(batch, update)
        if batch and batch['status'] in ('review', 'ready'):
            mode = st.radio('Conferência', ['Sequência', 'Dúvidas', 'Receitas'], horizontal=True,
                            index=0 if workflow.organization_pending(batch) else 1,
                            label_visibility='collapsed', key=f"review_mode_{batch['id']}")
            if mode == 'Sequência':
                try:
                    preferred = render_organization(batch)
                except (ValueError, OSError) as error:
                    st.error(str(error))
            elif mode == 'Dúvidas':
                preferred = render_questions(batch)
            else:
                render_recipes(batch)
            render_notes(batch)
            render_export(batch)
        render_history(batch)
    with right:
        render_preview(batch, preferred)


if __name__ == '__main__':
    main()
