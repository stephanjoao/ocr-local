from copy import deepcopy
import unittest
import pypdfium2 as pdfium
from studio import collect_questions, correct_occurrences, make_pdf


class StudioTests(unittest.TestCase):
    def recipe(self, title='Bolo'):
        return {'titulo': title, 'ingredientes': ['1 c.e. de açúcar', '100g de farinha'],
                'preparo': ['Misture & asse <com cuidado>.'], 'observacoes': [],
                'source': 'scan.png · página 1', 'warnings': []}

    def test_each_recipe_starts_on_separate_page_and_escapes_markup(self):
        pdf = make_pdf([self.recipe('Bolo & café'), self.recipe('Pão')])
        with pdfium.PdfDocument(pdf) as doc:
            self.assertEqual(len(doc), 2)
            first = doc[0].get_textpage().get_text_range()
            second = doc[1].get_textpage().get_text_range()
            self.assertIn('Bolo & café', first)
            self.assertNotIn('Pão', first)
            self.assertIn('Pão', second)
            self.assertIn('<com cuidado>', first)

    def test_repeated_questions_keep_all_sources(self):
        data = {'receitas': [self.recipe()], 'avisos': ['Conferir c.e.'], 'notas_pagina': []}
        questions = collect_questions([
            {'data': data, 'source': 'a.png', 'page': 1},
            {'data': deepcopy(data), 'source': 'b.png', 'page': 2}])
        self.assertEqual(len(questions), 2)
        self.assertTrue(all(len(question['sources']) == 2 for question in questions))

    def test_correction_is_literal_scoped_and_does_not_mutate_original(self):
        recipes = [self.recipe(), {**self.recipe(), 'source': 'other.png · página 1'}]
        result, count = correct_occurrences(recipes, {'sources': ['scan.png · página 1']},
                                            'c.e.', 'colher de sopa')
        self.assertEqual(count, 1)
        self.assertIn('colher de sopa', result[0]['ingredientes'][0])
        self.assertIn('c.e.', result[1]['ingredientes'][0])
        self.assertIn('c.e.', recipes[0]['ingredientes'][0])
        with self.assertRaises(ValueError):
            correct_occurrences(recipes, {'sources': []}, 'ausente', 'novo')

    def test_long_recipe_flows_instead_of_losing_text(self):
        recipe = self.recipe()
        recipe['preparo'] = ['Uma etapa longa para conferir a paginação. ' * 8] * 35
        with pdfium.PdfDocument(make_pdf([recipe])) as doc:
            self.assertGreater(len(doc), 1)


if __name__ == '__main__':
    unittest.main()
