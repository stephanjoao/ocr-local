"""Renderiza um PDF para inspeção visual, sem alterar o documento."""
import argparse
from pathlib import Path
import pypdfium2 as pdfium

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("pdf", type=Path)
parser.add_argument("--output", type=Path, default=Path("tmp/pdfs"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
with pdfium.PdfDocument(str(args.pdf.resolve())) as document:
    print(f"Páginas: {len(document)}")
    for index in range(len(document)):
        page = document[index]
        try:
            bitmap = page.render(scale=1.5)
            try:
                path = args.output / f"pagina-{index + 1:04}.png"
                bitmap.to_pil().save(path)
                print(path.resolve())
            finally:
                bitmap.close()
        finally:
            page.close()
