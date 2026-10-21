import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import pypdfium2 as pdfium
import ocr


class OCRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "scans"
        self.input.mkdir()
        self.output = self.root / "outputs"
        self.source = self.input / "receita.png"
        Image.new("RGB", (60, 80), "white").save(self.source)
        self.config = json.loads((ocr.ROOT / "config.json").read_text())
        self.success = {"message": {"content": "Bolo\n1/2 xícara de açúcar"},
                        "done": True, "done_reason": "stop", "eval_count": 12}

    def process(self, **kwargs):
        return ocr.process_file(
            self.source, self.source.relative_to(self.input), self.output,
            self.config, "Transcreva.", "modelo-teste", **kwargs)

    def make_tiff(self):
        self.source = self.input / "receitas.tiff"
        Image.new("RGB", (40, 60), "white").save(
            self.source, save_all=True, append_images=[Image.new("RGB", (40, 60), "gray")])

    def test_resume_integrity_and_original_preserved(self):
        original = self.source.read_bytes()
        with patch("ocr.transcribe", return_value=self.success) as model:
            first, _ = self.process()
            second, count = self.process()
            self.assertEqual(first[0]["status"], "ok")
            self.assertEqual(second[0]["status"], "skipped")
            self.assertEqual(count, 0)
            self.assertEqual(model.call_count, 1)
            text = next(self.output.rglob("*.txt"))
            text.write_text("arquivo alterado", encoding="utf-8")
            self.process()
            self.assertEqual(model.call_count, 2)
            self.assertIn("açúcar", text.read_text(encoding="utf-8"))
        self.assertEqual(self.source.read_bytes(), original)

    def test_changed_settings_preserve_previous_version(self):
        with patch("ocr.transcribe", return_value=self.success):
            self.process()
            self.config["max_image_side"] = 1600
            self.process()
        self.assertEqual(len(list(self.output.rglob("*.txt"))), 2)

    def test_truncated_response_retried(self):
        with patch("ocr.transcribe", return_value={**self.success, "done_reason": "length"}):
            records, _ = self.process()
        self.assertEqual(records[0]["status"], "incomplete")
        with patch("ocr.transcribe", return_value=self.success) as model:
            self.process()
            model.assert_called_once()

    def test_tiff_page_failure_does_not_stop_next_page(self):
        self.make_tiff()
        with patch("ocr.transcribe", side_effect=[RuntimeError("falha simulada"), self.success]):
            records, count = self.process()
        self.assertEqual(count, 2)
        self.assertEqual([r["status"] for r in records], ["error", "ok"])
        with patch("ocr.transcribe", return_value=self.success) as model:
            records, _ = self.process()
            model.assert_called_once()
            self.assertEqual([r["status"] for r in records], ["ok", "skipped"])

    def test_limit_resumes_next_page(self):
        self.make_tiff()
        with patch("ocr.transcribe", return_value=self.success) as model:
            records, count = self.process(remaining=1)
            self.assertEqual(count, 1)
            records, count = self.process(remaining=1)
            self.assertEqual([r["status"] for r in records], ["skipped", "ok"])
            self.assertEqual(count, 1)
            self.assertEqual(model.call_count, 2)

    def test_same_stem_different_extensions_do_not_collide(self):
        with patch("ocr.transcribe", return_value=self.success):
            self.process()
            self.source = self.input / "receita.jpg"
            Image.new("RGB", (60, 80), "white").save(self.source)
            self.process()
        self.assertEqual(len(list(self.output.rglob("*.txt"))), 2)

    def test_vision_api_receives_base64_and_no_history(self):
        with patch("ocr.api_request", return_value=self.success) as api:
            ocr.transcribe(b"image bytes", self.config, "Leia")
        route, body = api.call_args.args
        self.assertEqual(route, "/api/chat")
        self.assertFalse(body["stream"])
        self.assertEqual(len(body["messages"]), 1)
        self.assertEqual(base64.b64decode(body["messages"][0]["images"][0]), b"image bytes")

    def test_pdf_renders_all_pages_with_pixel_limit(self):
        path = self.input / "teste.pdf"
        with pdfium.PdfDocument.new() as document:
            for width, height in [(600, 800), (800, 600)]:
                page = document.new_page(width, height)
                page.close()
            document.save(str(path))
        pages = list(ocr.pages(path, {**self.config, "max_image_side": 400}))
        self.assertEqual([number for number, _ in pages], [1, 2])
        self.assertEqual([image.size for _, image in pages], [(300, 400), (400, 300)])

    def test_bad_file_continues_and_returns_error(self):
        (self.input / "a-corrompida.jpg").write_bytes(b"invalid image")
        with patch("ocr.check_model", return_value="test"), patch(
                "ocr.transcribe", return_value=self.success), patch("sys.stdout", new=io.StringIO()):
            code = ocr.main(["--input", str(self.input), "--output", str(self.output), "--no-review"])
        self.assertEqual(code, 1)
        self.assertEqual(len(list(self.output.rglob("*.txt"))), 1)
        self.assertFalse((self.output / ".ocr.lock").exists())

    def test_interrupt_releases_lock_and_can_resume(self):
        args = ["--input", str(self.input), "--output", str(self.output), "--no-review"]
        with patch("ocr.check_model", return_value="test"), patch(
                "ocr.transcribe", side_effect=KeyboardInterrupt), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(ocr.main(args), 130)
        self.assertFalse((self.output / ".ocr.lock").exists())
        with patch("ocr.check_model", return_value="test"), patch(
                "ocr.transcribe", return_value=self.success), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(ocr.main(args), 0)

    def test_overlapping_directories_rejected(self):
        with self.assertRaisesRegex(ValueError, "sobreposição"):
            ocr.main(["--input", str(self.input), "--output", str(self.input / "results")])


if __name__ == "__main__":
    unittest.main()
