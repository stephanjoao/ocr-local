from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ordering
import workflow
from settings import load_config, read_prompt
from test_workflow import analyzed_batch


def part(key, title=None):
    return {'id': key, 'titulo': title or key, 'source': f'{key}.png · página 1',
            'ingredientes': ['100g de açúcar'], 'preparo': ['Misture.'], 'observacoes': [],
            'warnings': [], 'include': True}


def link(a, b, kind='continuacao'):
    return {'antes': a, 'depois': b, 'tipo': kind, 'motivo': 'A indicação de continuação liga os dois trechos.'}


class OrderingTests(unittest.TestCase):
    def test_out_of_order_continuation_and_unrelated_recipe(self):
        recipes = [part('end'), part('other'), part('start')]
        groups = ordering.groups_from_links(recipes, [link('start', 'end')])
        self.assertEqual(groups, [['start', 'end'], ['other']])
        joined = ordering.materialize(recipes, groups)
        self.assertEqual(joined[0]['ingredientes'], ['100g de açúcar', '100g de açúcar'])
        self.assertEqual(joined[0]['sources'], ['start.png · página 1', 'end.png · página 1'])
        self.assertEqual(recipes[0]['id'], 'end')

    def test_explicit_order_reorders_distinct_recipes_without_merging(self):
        recipes = [part('b'), part('a'), part('c')]
        self.assertEqual(ordering.groups_from_links(recipes, [link('a', 'b', 'ordem')]), [['a'], ['b'], ['c']])

    def test_invalid_or_conflicting_links_are_rejected(self):
        recipes = [part('a'), part('b'), part('c')]
        for links in ([link('a', 'missing')], [link('a', 'a')], [link('a', 'b'), link('b', 'a')],
                      [link('a', 'b'), link('a', 'c')], [link('a', 'c'), link('b', 'c')],
                      [link('a', 'b', 'ordem'), link('b', 'a', 'ordem')]):
            with self.subTest(links=links), self.assertRaises(ValueError):
                ordering.groups_from_links(recipes, links)

    def test_groups_cannot_omit_or_duplicate_fragments(self):
        recipes = [part('a'), part('b')]
        for groups in ([['a']], [['a', 'a']], [['a', 'other']], [[]], 'a'):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                ordering.validate_groups(groups, recipes)

    def test_large_batch_uses_overlapping_windows_and_remote_title_pairs(self):
        recipes = [part(str(i), f'Prato {chr(65 + i)}') for i in range(20)]
        recipes[0]['titulo'] = 'Bolo de milho'
        recipes[-1]['titulo'] = 'Bolo de milho (continuação)'
        windows = ordering.comparison_groups(recipes, 1300)
        self.assertGreater(len(windows), 1)
        self.assertTrue(all(len(json.dumps(w, ensure_ascii=False)) <= 1300 for w in windows))
        self.assertEqual({x['id'] for w in windows for x in w}, {r['id'] for r in recipes})
        self.assertTrue(any({x['id'] for x in w} == {'0', '19'} for w in windows))

    def test_model_result_is_validated_and_truncation_is_rejected(self):
        recipes = [part('b'), part('a')]
        response = {'done': True, 'message': {'content': json.dumps({'ligacoes': [link('a', 'b')]})}}
        api = lambda *args, **kwargs: response
        result = ordering.suggest(recipes, load_config(), read_prompt('prompt_ordenacao.txt'), api)
        self.assertEqual(result['groups'], [['a', 'b']])
        response['done_reason'] = 'length'
        with self.assertRaisesRegex(ValueError, 'incompleta'):
            ordering.suggest(recipes, load_config(), read_prompt('prompt_ordenacao.txt'), api)

    def test_workflow_saves_suggestion_and_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = analyzed_batch(Path(directory), 2)
            ids = [r['id'] for r in batch['recipes']]
            original = deepcopy(batch['recipes'])
            proposal = {'groups': [ids[::-1]], 'links': [link(ids[1], ids[0])], 'comparisons': 1}
            with patch('ordering.suggest', return_value=proposal), patch('workflow.make_pdf') as pdf:
                workflow.organize_batch(batch, force=True)
                pdf.assert_not_called()
            self.assertEqual(batch['recipes'], original)
            self.assertTrue(workflow.organization_pending(batch))
            for question in batch['questions']:
                workflow.answer_question(batch, question['id'], 'keep')
            with self.assertRaisesRegex(ValueError, 'sequência'):
                workflow.export_pdf(batch, confirmed=True)
            workflow.confirm_organization(batch, True)
            loaded = workflow.load_batch(batch['directory'])
            with patch('workflow.make_pdf', return_value=b'%PDF') as pdf:
                workflow.export_pdf(loaded, confirmed=True)
            recipes = pdf.call_args.args[0]
            self.assertEqual(len(recipes), 1)
            self.assertEqual(recipes[0]['sources'][0], original[1]['source'])
            self.assertIn('Conferir açúcar?', recipes[0]['warnings'])

    def test_rejecting_or_failed_analysis_preserves_upload_order(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = analyzed_batch(Path(directory), 2)
            with patch('ordering.suggest', side_effect=ValueError('Conflito')):
                workflow.organize_batch(batch, force=True)
            self.assertTrue(workflow.organization_pending(batch))
            with self.assertRaisesRegex(ValueError, 'falhou'):
                workflow.confirm_organization(batch, True)
            workflow.confirm_organization(batch, False)
            self.assertFalse(workflow.organization_pending(batch))
            self.assertEqual(batch['organization']['groups'], ordering.identity_groups(batch['recipes']))

    def test_approved_sequence_survives_resume_and_new_text_corrections(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = analyzed_batch(Path(directory), 2)
            ids = [r['id'] for r in batch['recipes']]
            workflow.set_organization(batch, [ids[::-1]])
            workflow.confirm_organization(batch, True)
            updated = {**batch['recipes'][0], 'titulo': 'Título conferido'}
            workflow.edit_recipe(batch, updated['id'], updated)
            with patch('ordering.suggest') as model, patch('ocr.check_model', return_value='test'):
                workflow.analyze_batch(batch)
                model.assert_not_called()
            self.assertEqual(batch['organization']['groups'], [ids[::-1]])


if __name__ == '__main__':
    unittest.main()
