from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import editorial
import ocr


DATA = {
    "receitas": [{
        "titulo": "Bolo",
        "ingredientes": ["100 grs de açúcar", "200 ml de leite", "1 c.e. de manteiga"],
        "preparo": ["Misture e asse por 35 minutos."], "observacoes": [],
    }],
    "notas_pagina": [], "avisos": [],
    "alteracoes": [{"original": "Mistura", "corrigido": "Misture", "motivo": "Concordância."}],
}
RAW = "Bolo\n100 grs de açúcar\n200 ml de leite\n1 c.e. de manteiga\nMistura e asse por 35 minutos."
RESPONSE = {"done": True, "done_reason": "stop", "eval_count": 100,
            "message": {"content": json.dumps(DATA, ensure_ascii=False)}}


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "scan.png"
        Image.new("RGB", (40, 60), "white").save(self.source)
        self.output = self.root / "outputs"
        self.config = json.loads((ocr.ROOT / "config.json").read_text())

    def process(self, prompt="Revisar."):
        return ocr.process_file(
            self.source, Path("scan.png"), self.output, self.config,
            "Transcreva.", "model-test", review_prompt=prompt)

    def test_normalize_only_known_units(self):
        original = "100 grs, 90grs, 30 gramas, 200 ml, 1 kg, 1/2 xícara, 1 c.e., 30 grs."
        expected = "100g, 90g, 30g, 200ml, 1kg, 1/2 xícara, 1 c.e., 30g."
        self.assertEqual(editorial.normalize_units(original), expected)
        self.assertEqual(editorial.normalize_units("1,5 kg e 20 minutos"), "1,5kg e 20 minutos")

    def test_detects_changed_quantity_and_ambiguous_unit(self):
        changed = deepcopy(DATA)
        changed["receitas"][0]["ingredientes"][0] = "1000g de açúcar"
        result = editorial.normalize_and_audit(changed, RAW)
        self.assertTrue(any("números" in warning for warning in result["avisos"]))
        self.assertTrue(any("ambíguas" in warning for warning in result["avisos"]))

    def test_leading_zeros_and_fractions_not_false_number_change(self):
        self.assertEqual(editorial.number_counts("06 uvas, ½ xícara"), editorial.number_counts("6 uvas, 1/2 xícara"))

    def test_restores_ambiguous_measure_in_same_ingredient(self):
        self.assertEqual(editorial.preserve_ambiguous_units(
            "1/2 xícara de milho verde", "1/2 x de milho verde"), "1/2 x de milho verde")
        self.assertEqual(editorial.preserve_ambiguous_units(
            "1 colher de sopa de maionese", "01 c.e. de maionese"), "1 c.e. de maionese")
        self.assertEqual(editorial.preserve_ambiguous_units(
            "1 xícara de açúcar", "1 x de farinha"), "1 xícara de açúcar")

    def test_detects_grams_replaced_by_milliliters(self):
        changed = deepcopy(DATA)
        changed["receitas"][0]["ingredientes"][0] = "100ml de açúcar"
        result = editorial.normalize_and_audit(changed, RAW)
        self.assertTrue(any("unidades" in warning for warning in result["avisos"]))

    def test_missing_steps_are_flagged_not_invented(self):
        changed = deepcopy(DATA)
        changed["receitas"][0]["preparo"] = []
        result = editorial.normalize_and_audit(changed, RAW)
        self.assertEqual(result["receitas"][0]["preparo"], [])
        self.assertTrue(any("preparo ausente" in warning for warning in result["avisos"]))

    def test_schema_rejects_wrong_types(self):
        changed = deepcopy(DATA)
        changed["receitas"][0]["ingredientes"] = "100g"
        with self.assertRaises(ValueError):
            editorial.validate(changed)

    def test_latex_escapes_data_instead_of_executing_commands(self):
        escaped = editorial.tex_escape(r"100% & açúcar_1 \input{segredo} # $")
        self.assertNotIn(r"\input{segredo}", escaped)
        self.assertIn(r"\textbackslash{}input\{segredo\}", escaped)
        self.assertIn(r"100\%", escaped)

    def test_two_stages_resume_and_new_prompt_preserves_ocr(self):
        raw_response = {**RESPONSE, "message": {"content": RAW}}
        with patch("ocr.transcribe", return_value=raw_response) as raw, patch(
                "ocr.api_request", return_value=RESPONSE) as review:
            records, count = self.process()
            self.assertEqual(records[0]["review_status"], "ok")
            self.assertEqual(count, 1)
            records, count = self.process()
            self.assertEqual(records[0]["review_status"], "skipped")
            self.assertEqual(count, 0)
            self.process("Outro prompt.")
            self.assertEqual(raw.call_count, 1)
            self.assertEqual(review.call_count, 2)
            self.assertEqual(len(list(self.output.rglob("*.receitas.json"))), 2)
        self.assertEqual(next(self.output.rglob("*.txt")).read_text(encoding="utf-8"), RAW + "\n")

    def test_revision_failure_preserves_raw_and_retries_only_review(self):
        with patch("ocr.transcribe", return_value={**RESPONSE, "message": {"content": RAW}}) as raw:
            with patch("ocr.api_request", return_value={**RESPONSE, "done_reason": "length"}):
                records, _ = self.process()
                self.assertEqual(records[0]["review_status"], "error")
            self.assertEqual(next(self.output.rglob("*.txt")).read_text(encoding="utf-8"), RAW + "\n")
            with patch("ocr.api_request", return_value=RESPONSE):
                records, _ = self.process()
                self.assertEqual(records[0]["review_status"], "ok")
            self.assertEqual(raw.call_count, 1)

    def test_book_does_not_collect_stale_revisions(self):
        with patch("ocr.transcribe", return_value={**RESPONSE, "message": {"content": RAW}}), patch(
                "ocr.api_request", return_value=RESPONSE):
            records, _ = self.process()
            self.process("Versão diferente.")
        book = editorial.build_book(records, self.output, "test-run", ocr.atomic_write, ocr.write_json)
        text = book.read_text(encoding="utf-8")
        self.assertEqual(text.count(r"\section*{Bolo}"), 1)
        self.assertIn("100g", text)
        self.assertIn(r"\end{document}", text)


if __name__ == "__main__":
    unittest.main()
