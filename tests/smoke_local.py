"""Teste opcional real: Ollama local, imagem sintética e fluxo com conferência."""
from pathlib import Path
import sys
import tempfile
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
import reportlab
import workflow
from settings import load_config


def main():
    with tempfile.TemporaryDirectory(prefix='ocr-local-smoke-') as directory:
        image = Image.new('RGB', (1000, 900), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf'), 32)
        text = ('Bolo de milho\n\n2 ovos\n1/2 xícara de açúcar\n200 ml de leite\n'
                '\nMisture e asse por 35 minutos.\n\nTelefone do encanador: 5555-4321')
        draw.multiline_text((55, 45), text, font=font, fill='black', spacing=15)
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        batch = workflow.create_batch([('receita-teste.png', buffer.getvalue())], load_config(), Path(directory))
        workflow.analyze_batch(batch, lambda p, title, detail: print(f'{p:.0%} {title} · {detail}', flush=True))
        assert not batch['failures'], batch['failures']
        assert batch['recipes'], 'Nenhuma receita reconhecida.'
        assert batch['pdf'] is None, 'PDF gerado antes das respostas.'
        raw = next((Path(batch['directory']) / 'processamento').rglob('*.txt')).read_text(encoding='utf-8')
        for fragment in ('2 ovos', '1/2', '200', '35'):
            assert fragment in raw, f'Não reconheceu: {fragment}'
        for question in batch['questions']:
            workflow.answer_question(batch, question['id'], 'keep', note='Teste automático: preservar avisos.')
        pdf = workflow.export_pdf(batch, confirmed=True)
        assert pdf.read_bytes().startswith(b'%PDF')
        print('Leitura, conferência e PDF concluídos. Precisão em cursiva não avaliada.')


if __name__ == '__main__':
    main()
