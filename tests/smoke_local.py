"""Teste opcional real: usa o Ollama local e uma imagem sintética impressa."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
import ocr


def main():
    with tempfile.TemporaryDirectory(prefix="ocr-local-smoke-") as directory:
        root = Path(directory)
        scans = root / "scans"
        scans.mkdir()
        image = Image.new("RGB", (1000, 700), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 38)
        expected = "Bolo de milho\n\n2 ovos\n1/2 xícara de açúcar\n200 ml de leite\n\nMisture e asse por 35 minutos."
        draw.multiline_text((55, 45), expected, font=font, fill="black", spacing=15)
        image.save(scans / "receita-teste.png")
        output = root / "outputs"
        args = ["--input", str(scans), "--output", str(output)]
        assert ocr.main(args) == 0, "O OCR real falhou."
        text = next(output.rglob("*.txt")).read_text(encoding="utf-8")
        print("\nTRANSCRIÇÃO REAL:\n" + text)
        for fragment in ("2 ovos", "1/2", "200", "35"):
            assert fragment in text, f"Não reconheceu: {fragment}"
        assert ocr.main(args) == 0, "A retomada falhou."
        reports = [json.loads(p.read_text(encoding="utf-8")) for p in (output / "_runs").glob("*.json")]
        assert any(r["pages"][0]["status"] == "skipped" for r in reports)
        print("Teste real e retomada concluídos. Precisão em cursiva ainda não avaliada.")


if __name__ == "__main__":
    main()
