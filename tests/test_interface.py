from pathlib import Path
import tempfile
import unittest

from streamlit.testing.v1 import AppTest
from test_workflow import analyzed_batch
import workflow


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.batch = analyzed_batch(Path(self.temp.name))
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app_streamlit.py'), default_timeout=15)
        self.app.session_state['active_batch'] = self.batch
        self.app.run()
        self.assertFalse(self.app.exception)

    def button(self, label):
        return next(button for button in self.app.button if button.label == label)

    def test_answers_precede_generation_and_pdf_preview_renders(self):
        self.assertTrue(self.button('Gerar PDF').disabled)
        self.assertIsNone(self.app.session_state['active_batch']['pdf'])
        while workflow.pending_questions(self.app.session_state['active_batch']):
            action = next(radio for radio in self.app.radio if radio.label == 'Como você quer tratar este ponto?')
            action.set_value('keep').run()
            self.button('Salvar resposta').click().run()
            self.assertFalse(self.app.exception)
            self.assertIsNone(self.app.session_state['active_batch']['pdf'])
        self.assertFalse(self.button('Gerar PDF').disabled)
        next(box for box in self.app.checkbox if box.label == 'Conferi as receitas e quero gerar o PDF').check()
        self.button('Gerar PDF').click().run()
        self.assertFalse(self.app.exception)
        batch = self.app.session_state['active_batch']
        self.assertTrue((Path(batch['directory']) / batch['pdf']).exists())
        self.assertTrue(any(select.label == 'Página do PDF' for select in self.app.selectbox))
        self.assertEqual(self.app.get('progress')[0].proto.value, 100)

    def test_recipe_form_saves_and_does_not_generate_pdf(self):
        next(radio for radio in self.app.radio if radio.label == 'Conferência').set_value('Receitas').run()
        next(field for field in self.app.text_input if field.label == 'Título').set_value('Bolo da família')
        self.button('Salvar receita').click().run()
        self.assertFalse(self.app.exception)
        batch = self.app.session_state['active_batch']
        self.assertEqual(workflow.load_batch(batch['directory'])['recipes'][0]['titulo'], 'Bolo da família')
        self.assertIsNone(batch['pdf'])

    def test_sequence_suggestion_is_confirmed_before_pdf(self):
        batch = analyzed_batch(Path(self.temp.name), 2)
        ids = [r['id'] for r in batch['recipes']]
        workflow.set_organization(batch, [ids[::-1]])
        self.app.session_state['active_batch'] = batch
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertTrue(self.button('Gerar PDF').disabled)
        self.button('Usar esta sequência').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state['active_batch']['organization']['status'], 'approved')
        self.assertIsNone(self.app.session_state['active_batch']['pdf'])


if __name__ == '__main__':
    unittest.main()
