from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import caderno
import workflow
from test_workflow import analyzed_batch


class CLITests(unittest.TestCase):
    def test_terminal_asks_about_sequence_before_ocr_questions(self):
        with tempfile.TemporaryDirectory() as root:
            batch = analyzed_batch(Path(root), 2)
            workflow.set_organization(batch, [[r['id'] for r in reversed(batch['recipes'])]])
            with patch('builtins.input', side_effect=['m', 'm']), redirect_stdout(StringIO()):
                caderno.review_interactively(batch)
            self.assertEqual(batch['organization']['status'], 'kept')
            self.assertFalse(workflow.pending_questions(batch))
            self.assertIsNone(batch['pdf'])

    def test_pdf_command_obeys_the_same_review_gate(self):
        with tempfile.TemporaryDirectory() as root:
            batch = analyzed_batch(Path(root))
            with self.assertRaisesRegex(ValueError, 'pendentes'):
                caderno.main(['pdf', batch['directory'], '--confirmar'])
            for question in batch['questions']:
                workflow.answer_question(batch, question['id'], 'keep')
            with redirect_stdout(StringIO()):
                self.assertEqual(caderno.main(['pdf', batch['directory'], '--confirmar']), 0)
            self.assertIsNotNone(workflow.load_batch(batch['directory'])['pdf'])

    def test_inputs_deduplicate_and_keep_explicit_order(self):
        with tempfile.TemporaryDirectory() as root:
            first, second = Path(root) / 'b.png', Path(root) / 'a.pdf'
            first.write_bytes(b'image')
            second.write_bytes(b'pdf')
            self.assertEqual(caderno.input_files([first, second, first]), [first, second])

    def test_interrupted_lot_cannot_enter_review(self):
        with tempfile.TemporaryDirectory() as root:
            batch = analyzed_batch(Path(root))
            batch['status'] = 'interrupted'
            workflow.save_batch(batch)
            with self.assertRaisesRegex(ValueError, 'Retome'):
                caderno.main(['conferir', batch['directory']])


if __name__ == '__main__':
    unittest.main()
