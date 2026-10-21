"""OCR local de scans, com saídas por página e retomada verificável."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

from PIL import Image, ImageOps
import pypdfium2 as pdfium
import editorial
from settings import load_config

ROOT = Path(__file__).resolve().parent
API = "http://127.0.0.1:11434"
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}
PIPELINE_VERSION = 1
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes):
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def api_request(route, payload=None, timeout=20):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        API + route, data=body, headers={"Content-Type": "application/json"}
    )
    # Não encaminhar scans para proxies configurados no sistema.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Ollama HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(
            f"Não foi possível consultar {API}. Abra o Ollama e tente novamente. "
            f"Detalhe: {error}"
        ) from error
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result


def check_model(config):
    models = api_request("/api/tags").get("models", [])
    match = next((m for m in models if config["model"] in
                  (m.get("name"), m.get("model"))), None)
    if not match:
        raise RuntimeError(
            f"Modelo ausente. Execute: ollama pull {config['model']}"
        )
    info = api_request("/api/show", {"model": config["model"]})
    if "vision" not in info.get("capabilities", []):
        raise RuntimeError("O modelo escolhido não informa suporte a imagens.")
    return match["digest"]


def prepare_image(image, max_side):
    image = ImageOps.exif_transpose(image)
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    rgb = background.convert("RGB")
    rgb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return rgb


def pages(path: Path, config):
    """Renderiza uma página por vez, incluindo TIFF multipágina."""
    if path.suffix.lower() == ".pdf":
        with pdfium.PdfDocument(str(path)) as document:
            for index in range(len(document)):
                page = document[index]
                try:
                    width, height = page.get_size()
                    scale = min(config["pdf_dpi"] / 72,
                                config["max_image_side"] / max(width, height))
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                yield index + 1, prepare_image(image, config["max_image_side"])
    else:
        with Image.open(path) as image:
            for index in range(getattr(image, "n_frames", 1)):
                image.seek(index)
                yield index + 1, prepare_image(image.copy(), config["max_image_side"])


def page_count(path):
    """Conta as páginas sem renderizar o documento inteiro."""
    if path.suffix.lower() == ".pdf":
        with pdfium.PdfDocument(str(path)) as document:
            return len(document)
    with Image.open(path) as image:
        return getattr(image, "n_frames", 1)


def transcribe(image_bytes, config, prompt):
    return api_request("/api/chat", {
        "model": config["model"],
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
        }],
        "stream": False,
        "keep_alive": "5m",
        "options": {key: config[key] for key in
                    ("num_ctx", "num_predict", "temperature")},
    }, timeout=config["timeout_seconds"])


def reusable(metadata_path, text_path, image_path):
    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        return (meta.get("status") == "ok"
                and meta["text_sha256"] == file_digest(text_path)
                and meta["image_sha256"] == file_digest(image_path))
    except (OSError, ValueError, KeyError):
        return False


def apply_review(prefix, record, config, review_prompt, model_digest, force=False):
    try:
        result = editorial.review_page(
            prefix, record, config, review_prompt, model_digest,
            api_request, write_json, atomic_write, force)
        return {**record, **result}
    except Exception as error:
        logger.error("Página %s: erro na revisão: %s", record['page'], error)
        return {**record, "status": "error", "review_status": "error", "error": str(error)}


def process_file(source, relative, output, config, prompt, model_digest,
                 force=False, remaining=None, review_prompt=None, progress=None):
    # Alterar o prompt editorial não exige repetir o OCR já concluído.
    ocr_config = {key: config[key] for key in (
        "model", "num_ctx", "num_predict", "temperature", "max_image_side",
        "pdf_dpi", "timeout_seconds")}
    identity = {
        "source_sha256": file_digest(source),
        "model_digest": model_digest,
        "config": ocr_config,
        "prompt": prompt,
        "pipeline_version": PIPELINE_VERSION,
    }
    fingerprint = digest(json.dumps(identity, sort_keys=True).encode())
    directory = output / relative / fingerprint[:16]
    records = []
    attempted = 0
    for number, image in pages(source, config):
        if progress:
            progress(number, "Preparando página")
        prefix = directory / f"pagina-{number:04}"
        text_path = prefix.with_suffix(".txt")
        meta_path = prefix.with_suffix(".json")
        image_path = prefix.with_suffix(".png")
        record = {"source": relative.as_posix(), "page": number,
                  "metadata": meta_path.relative_to(output).as_posix()}
        if not force and reusable(meta_path, text_path, image_path):
            entry = {**record, "status": "skipped"}
            if review_prompt is not None:
                base, _ = editorial.review_paths(prefix, config, review_prompt, model_digest)
                pending = not editorial.review_reusable(base)
                if pending and remaining is not None and attempted >= remaining:
                    break
                attempted += int(pending)
                if progress:
                    progress(number, "Revisando e filtrando receitas")
                entry = apply_review(prefix, entry, config, review_prompt, model_digest)
            logger.info("Página %s: OCR já concluído.", number)
            records.append(entry)
            if progress:
                progress(number, "Página concluída")
            continue
        if remaining is not None and attempted >= remaining:
            break
        attempted += 1
        directory.mkdir(parents=True, exist_ok=True)
        image_buffer = io.BytesIO()
        image.save(image_buffer, format="PNG")
        image_bytes = image_buffer.getvalue()
        image_path.write_bytes(image_bytes)
        meta = {**record, **identity, "fingerprint": fingerprint,
                "created_at": now(), "image_size": list(image.size),
                "image_sha256": digest(image_bytes), "human_review_required": True}
        # Invalidar qualquer execução anterior antes de chamar o modelo.
        write_json(meta_path, {**meta, "status": "processing"})
        started = time.monotonic()
        logger.info("Página %s: lendo…", number)
        try:
            if progress:
                progress(number, "Lendo texto da imagem")
            response = transcribe(image_bytes, config, prompt)
            text = response.get("message", {}).get("content", "").strip()
            if not text:
                raise RuntimeError("O modelo retornou uma transcrição vazia.")
            warnings = []
            incomplete = (response.get("done") is not True
                          or response.get("done_reason") == "length"
                          or response.get("eval_count", 0) >= config["num_predict"])
            if incomplete:
                warnings.append("Resposta possivelmente truncada; reprocessar com limite maior.")
            if "[ilegível]" in text.lower() or "[dúvida:" in text.lower():
                warnings.append("O modelo marcou trechos ilegíveis ou duvidosos.")
            atomic_write(text_path, text + "\n")
            status = "incomplete" if incomplete else "ok"
            write_json(meta_path, {
                **meta, "status": status, "warnings": warnings,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "text_sha256": file_digest(text_path),
                "response": response,
            })
            entry = {**record, "status": status, "warnings": warnings}
            if status == "ok" and review_prompt is not None:
                if progress:
                    progress(number, "Revisando e filtrando receitas")
                entry = apply_review(prefix, entry, config, review_prompt, model_digest, force)
            records.append(entry)
            logger.info("Página %s: %s", number, status)
        except Exception as error:
            write_json(meta_path, {**meta, "status": "error", "error": str(error)})
            records.append({**record, "status": "error", "error": str(error)})
            logger.error("Página %s: %s", number, error)
        if progress:
            progress(number, "Página concluída")
    return records, attempted


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Use um inteiro maior que zero.")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "scans")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompt.txt")
    parser.add_argument("--check", action="store_true", help="Verificar Ollama e modelo.")
    parser.add_argument("--limit", type=positive_int, help="Máximo de páginas novas a tentar.")
    parser.add_argument("--force", action="store_true", help="Reprocessar saídas desta versão.")
    parser.add_argument("--no-review", action="store_true", help="Executar apenas OCR literal.")
    parser.add_argument("--review-prompt", type=Path, default=ROOT / "prompt_revisao.txt")
    parser.add_argument("--compile", action="store_true", help="Compilar o livro LaTeX em PDF.")
    parser.add_argument("--compile-tex", type=Path, help="Compilar um .tex existente, sem OCR.")
    args = parser.parse_args(argv)
    if args.compile_tex:
        tex = args.compile_tex.resolve()
        if not tex.is_file() or tex.suffix.lower() != ".tex":
            raise ValueError("Informe um arquivo .tex existente.")
        print(f"PDF: {editorial.compile_latex(tex)}")
        return 0
    config = load_config(args.config)
    review_enabled = config.get("review_enabled", True) and not args.no_review
    if args.compile and not review_enabled:
        raise ValueError("--compile exige revisão habilitada.")
    review_prompt = args.review_prompt.read_text(encoding="utf-8-sig").strip() if review_enabled else None
    if review_enabled and not review_prompt:
        raise ValueError("O prompt de revisão não pode estar vazio.")
    prompt = args.prompt.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise ValueError("O prompt não pode estar vazio.")
    if args.check:
        model_digest = check_model(config)
        print(f"Ollama pronto: {config['model']} ({model_digest[:12]}).")
        return 0
    input_dir, output_dir = args.input.resolve(), args.output.resolve()
    if input_dir == output_dir or input_dir in output_dir.parents or output_dir in input_dir.parents:
        raise ValueError("As pastas de entrada e saída devem ser separadas, sem sobreposição.")
    if not input_dir.is_dir():
        raise ValueError(f"Pasta de scans não encontrada: {input_dir}")
    sources = sorted((p for p in input_dir.rglob("*")
                      if p.is_file() and not p.is_symlink()
                      and p.suffix.lower() in EXTENSIONS),
                     key=lambda p: p.relative_to(input_dir).as_posix().casefold())
    if not sources:
        print(f"Coloque imagens ou PDFs em {input_dir} e execute novamente.")
        return 0
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / ".ocr.lock"
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError:
        raise RuntimeError(
            f"Já existe um processamento ou trava antiga: {lock_path}. "
            "Se nenhum OCR estiver rodando, remova apenas esse arquivo e tente novamente."
        )
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_path = output_dir / "_runs" / f"{run_id}.json"
    report = {"started_at": now(), "status": "running", "pages": [], "files_with_errors": []}
    try:
        with lock:
            lock.write(now())
        model_digest = check_model(config)
        attempts = 0
        for source in sources:
            if args.limit is not None and attempts >= args.limit:
                break
            relative = source.relative_to(input_dir)
            print(f"\nArquivo: {relative}", flush=True)
            try:
                records, count = process_file(
                    source, relative, output_dir, config, prompt, model_digest,
                    args.force, None if args.limit is None else args.limit - attempts,
                    review_prompt=review_prompt)
                report["pages"].extend(records)
                attempts += count
            except Exception as error:
                report["files_with_errors"].append({"source": relative.as_posix(), "error": str(error)})
                print(f"ERRO no arquivo {relative}: {error}", file=sys.stderr)
            write_json(run_path, report)
        failed = bool(report["files_with_errors"]) or any(
            page["status"] in ("error", "incomplete") for page in report["pages"])
        if review_enabled:
            book = editorial.build_book(report["pages"], output_dir, run_id, atomic_write, write_json)
            if book:
                report["book_tex"] = str(book)
                print(f"\nLivro LaTeX: {book}", flush=True)
                if args.compile:
                    report["book_pdf"] = str(editorial.compile_latex(book))
                    print(f"Livro PDF: {report['book_pdf']}", flush=True)
        report["status"] = "finished_with_errors" if failed else "finished"
        print(f"\nRelatório: {run_path}")
        return 1 if failed else 0
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        print("\nInterrompido. Execute novamente para retomar.", file=sys.stderr)
        return 130
    except Exception:
        report["status"] = "failed"
        raise
    finally:
        report["finished_at"] = now()
        try:
            write_json(run_path, report)
        finally:
            lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(1)
