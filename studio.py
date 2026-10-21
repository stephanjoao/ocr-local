"""Composição do livro e agrupamento de dúvidas da interface."""
from collections import OrderedDict
from copy import deepcopy
from io import BytesIO
import hashlib
from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import reportlab


def collect_questions(pages):
    groups = OrderedDict()
    for page in pages:
        data = page['data']
        texts = list(data['avisos'])
        for recipe in data['receitas']:
            for field in ('titulo', 'ingredientes', 'preparo', 'observacoes'):
                value = recipe[field]
                text = value if isinstance(value, str) else '\n'.join(value)
                texts.extend(re.findall(r'\[(?:dúvida:[^\]]*|ilegível)\]', text, re.I))
        for text in dict.fromkeys(texts):
            key = ' '.join(text.casefold().split())
            group = groups.setdefault(key, {'text': text, 'sources': [], 'original': ''})
            source = f"{page['source']} · página {page['page']}"
            if source not in group['sources']:
                group['sources'].append(source)
            if re.fullmatch(r'\[(?:dúvida:[^\]]*|ilegível)\]', text, re.I):
                group['original'] = text
        for recipe in data['receitas']:
            text = '\n'.join(recipe['ingredientes'] + recipe['preparo'] + recipe['observacoes'])
            for match in re.finditer(r'\bc\.\s*[ec]\.|(?<=\d)\s+(x)\b', text, re.I):
                original = match.group().strip()
                key = 'abreviacao:' + original.casefold()
                group = groups.setdefault(key, {
                    'text': f'O que significa “{original}”? Confirme a medida antes de expandir a abreviação.',
                    'sources': [], 'original': original,
                })
                source = f"{page['source']} · página {page['page']}"
                if source not in group['sources']:
                    group['sources'].append(source)
    for key, question in groups.items():
        identity = key + '\n' + '\n'.join(question['sources'])
        question['id'] = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return list(groups.values())


def make_pdf(recipes):
    """Cada receita começa em uma folha; receitas longas podem continuar."""
    if not recipes:
        raise ValueError('Nenhuma receita para gerar o PDF.')
    target = BytesIO()
    # A fonte acompanha ReportLab; não depende de fontes ou downloads do sistema.
    fonts = Path(reportlab.__file__).parent / 'fonts'
    if 'Caderno' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('Caderno', str(fonts / 'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('Caderno-Bold', str(fonts / 'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('Caderno', normal='Caderno', bold='Caderno-Bold')
    styles = getSampleStyleSheet()
    for name in ('Normal', 'BodyText'):
        styles[name].fontName = 'Caderno'
    styles['Heading2'].fontName = 'Caderno-Bold'
    styles.add(ParagraphStyle(name='RecipeTitle', fontName='Caderno-Bold', fontSize=23,
                              leading=28, textColor=colors.HexColor('#34483e'), spaceAfter=20))
    styles['BodyText'].leading = 16
    styles['BodyText'].fontSize = 10.5
    styles['Heading2'].textColor = colors.HexColor('#34483e')
    story = []
    for index, recipe in enumerate(recipes):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(escape(recipe['titulo']), styles['RecipeTitle']))
        story.append(Paragraph(escape(recipe['source']), styles['Normal']))
        story.append(Spacer(1, 14))
        for field, title in [('ingredientes', 'Ingredientes'), ('preparo', 'Modo de preparo'),
                             ('observacoes', 'Observações')]:
            lines = recipe[field]
            if not lines:
                continue
            story.append(Paragraph(title, styles['Heading2']))
            for number, line in enumerate(lines, 1):
                prefix = f'{number}. ' if field == 'preparo' else '• '
                story.append(Paragraph(escape(prefix + line), styles['BodyText']))
        if not recipe['preparo']:
            story.append(Paragraph('Modo de preparo ausente no original.', styles['BodyText']))
        if recipe.get('warnings'):
            story.append(Paragraph('Para conferir', styles['Heading2']))
            for warning in recipe['warnings']:
                story.append(Paragraph(escape(warning), styles['BodyText']))
    def footer(canvas, doc):
        canvas.setFont('Caderno', 8)
        canvas.setFillColor(colors.HexColor('#6b756e'))
        canvas.drawString(46, 25, 'Caderno de receitas · edição para conferência')
        canvas.drawRightString(A4[0] - 46, 25, str(doc.page))
    SimpleDocTemplate(target, pagesize=A4, rightMargin=46, leftMargin=46,
                      topMargin=46, bottomMargin=46, title='Caderno de receitas').build(
                          story, onFirstPage=footer, onLaterPages=footer)
    return target.getvalue()


def correct_occurrences(recipes, question, original, replacement):
    """Aplica somente uma substituição literal fornecida pela pessoa."""
    if not original.strip() or not replacement.strip():
        raise ValueError('Preencha o trecho original e a leitura correta.')
    result = deepcopy(recipes)
    count = 0
    pattern = re.compile((r'(?<!\w)' if original[0].isalnum() else '') + re.escape(original)
                         + (r'(?!\w)' if original[-1].isalnum() else ''))
    for recipe in result:
        if recipe['source'] not in question['sources']:
            continue
        for field in ('titulo', 'ingredientes', 'preparo', 'observacoes'):
            value = recipe[field]
            if isinstance(value, str):
                recipe[field], occurrences = pattern.subn(lambda match: replacement, value)
                count += occurrences
            else:
                replacements = [pattern.subn(lambda match: replacement, line) for line in value]
                count += sum(occurrences for _, occurrences in replacements)
                recipe[field] = [line for line, _ in replacements]
    if not count:
        raise ValueError('Trecho não encontrado nas receitas indicadas. Confira a grafia exata.')
    return result, count
