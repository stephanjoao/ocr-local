from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import pypdfium2 as pdfium
import workflow
import ordering
from settings import load_config, validate_config


DATA = {'receitas': [{'titulo': 'Bolo', 'ingredientes': ['100g de açúcar'],
                     'preparo': ['Misture e asse.'], 'observacoes': []}],
        'notas_pagina': ['Telefone de contato: 1234'], 'avisos': ['Conferir açúcar?'], 'alteracoes': []}
RESPONSE = {'done': True, 'done_reason': 'stop', 'eval_count': 100,
            'message': {'content': json.dumps(DATA)}}


def image_bytes():
    image = BytesIO()
    Image.new('RGB', (30, 40), 'white').save(image, format='PNG')
    return image.getvalue()


def analyzed_batch(root, count=1):
    batch = workflow.create_batch([(f'{i}.png', image_bytes()) for i in range(count)], load_config(), root)
    with patch('ocr.check_model', return_value='test'), patch('ocr.transcribe', return_value={
            **RESPONSE, 'message': {'content': 'Bolo 100g de açúcar. Telefone de contato: 1234'}}), patch(
            'ocr.api_request', return_value=RESPONSE), patch('ordering.suggest',
            side_effect=lambda recipes, *args: {'groups': ordering.identity_groups(recipes), 'links': [], 'comparisons': 1}):
        workflow.analyze_batch(batch)
    return batch


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reading_groups_questions_and_never_generates_pdf(self):
        with patch('workflow.make_pdf') as pdf:
            batch = analyzed_batch(self.root, count=2)
            pdf.assert_not_called()
        self.assertEqual(len(batch['pages']), 2)
        self.assertEqual(len(batch['recipes']), 2)
        self.assertIsNone(batch['pdf'])
        self.assertFalse(list(self.root.rglob('*.pdf')))
        self.assertTrue(Path(batch['pages'][0]['preview']).exists())
        self.assertEqual(len(workflow.pending_questions(batch)[0]['sources']), 2)

    def test_pdf_requires_all_answers_and_explicit_confirmation(self):
        batch = analyzed_batch(self.root)
        with self.assertRaisesRegex(ValueError, 'todas as dúvidas'):
            workflow.export_pdf(batch, confirmed=True)
        for question in batch['questions']:
            workflow.answer_question(batch, question['id'], 'keep')
        self.assertIsNone(batch['pdf'])
        with self.assertRaisesRegex(ValueError, 'Confirme'):
            workflow.export_pdf(batch)
        path = workflow.export_pdf(batch, confirmed=True)
        with pdfium.PdfDocument(path.read_bytes()) as doc:
            text = doc[0].get_textpage().get_text_range()
            self.assertNotIn('Telefone de contato: 1234', text)
            self.assertIn('Conferir açúcar?', text)

    def test_edits_and_answers_survive_reload_and_invalidate_pdf(self):
        batch = analyzed_batch(self.root)
        for question in batch['questions']:
            workflow.answer_question(batch, question['id'], 'checked')
        old_pdf = workflow.export_pdf(batch, confirmed=True)
        recipe = {**batch['recipes'][0], 'titulo': 'Bolo de família'}
        workflow.edit_recipe(batch, recipe['id'], recipe)
        loaded = workflow.load_batch(batch['directory'])
        self.assertIsNone(loaded['pdf'])
        self.assertEqual(loaded['recipes'][0]['titulo'], 'Bolo de família')
        self.assertFalse(workflow.pending_questions(loaded))
        self.assertTrue(old_pdf.exists())

    def test_partial_pdf_requires_explicit_choice(self):
        batch = analyzed_batch(self.root)
        for question in batch['questions']:
            workflow.answer_question(batch, question['id'], 'checked')
        batch['failures'] = ['Página danificada']
        workflow.save_batch(batch)
        with self.assertRaisesRegex(ValueError, 'parcial'):
            workflow.export_pdf(batch, confirmed=True)
        self.assertTrue(workflow.export_pdf(batch, confirmed=True, allow_partial=True).exists())

    def test_answer_corrects_repeated_occurrences_without_generating(self):
        batch = analyzed_batch(self.root, 2)
        q = next(q for q in batch['questions'] if q['text'] == 'Conferir açúcar?')
        with patch('workflow.make_pdf') as pdf:
            count = workflow.answer_question(batch, q['id'], 'correct', 'açúcar', 'açúcar mascavo')
            pdf.assert_not_called()
        self.assertEqual(count, 2)
        self.assertTrue(all('mascavo' in r['ingredientes'][0] for r in batch['recipes']))

    def test_conflicting_session_cannot_overwrite_answers(self):
        batch = analyzed_batch(self.root)
        stale = deepcopy(batch)
        workflow.answer_question(batch, batch['questions'][0]['id'], 'keep')
        with self.assertRaisesRegex(ValueError, 'outra sessão'):
            workflow.answer_question(stale, stale['questions'][0]['id'], 'checked')
        self.assertEqual(workflow.load_batch(batch['directory'])['answers'][batch['questions'][0]['id']]['action'], 'keep')

    def test_resume_does_not_repeat_ocr_or_erase_human_edit(self):
        batch = analyzed_batch(self.root)
        recipe = {**batch['recipes'][0], 'titulo': 'Título conferido'}
        workflow.edit_recipe(batch, recipe['id'], recipe)
        with patch('ocr.check_model', return_value='test'), patch('ocr.transcribe') as transcribe:
            workflow.analyze_batch(batch)
            transcribe.assert_not_called()
        self.assertEqual(batch['recipes'][0]['titulo'], 'Título conferido')

    def test_interrupted_batch_is_persisted_and_unlocked(self):
        batch = workflow.create_batch([('a.png', image_bytes())], load_config(), self.root)
        with patch('ocr.check_model', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                workflow.analyze_batch(batch)
        self.assertEqual(workflow.load_batch(batch['directory'])['status'], 'interrupted')
        self.assertFalse((Path(batch['directory']) / '.processing.lock').exists())

    def test_config_rejects_invalid_model_and_temperature(self):
        for patch_values in ({'model': ''}, {'temperature': float('nan')}, {'num_ctx': True}):
            with self.assertRaises(ValueError):
                validate_config({**load_config(), **patch_values})


if __name__ == '__main__':
    unittest.main()
