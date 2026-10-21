"""Revisão visual, normalização conservadora e composição LaTeX."""
from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

VERSION = 2
STRINGS = {"type": "array", "items": {"type": "string"}}
RECIPE = {
    "type": "object",
    "properties": {"titulo": {"type": "string"}, "ingredientes": STRINGS,
                   "preparo": STRINGS, "observacoes": STRINGS},
    "required": ["titulo", "ingredientes", "preparo", "observacoes"],
    "additionalProperties": False,
}
CHANGE = {
    "type": "object",
    "properties": {key: {"type": "string"} for key in ("original", "corrigido", "motivo")},
    "required": ["original", "corrigido", "motivo"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "receitas": {"type": "array", "items": RECIPE},
        "notas_pagina": STRINGS, "avisos": STRINGS,
        "alteracoes": {"type": "array", "items": CHANGE},
    },
    "required": ["receitas", "notas_pagina", "avisos", "alteracoes"],
    "additionalProperties": False,
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate(value, schema=SCHEMA, field="resposta"):
    expected = schema["type"]
    if expected == "object":
        if not isinstance(value, dict) or set(value) != set(schema["required"]):
            raise ValueError(f"Campos inválidos em {field}.")
        for key, subschema in schema["properties"].items():
            validate(value[key], subschema, f"{field}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise ValueError(f"{field} deve ser uma lista.")
        for item in value:
            validate(item, schema["items"], field)
    elif not isinstance(value, str):
        raise ValueError(f"{field} deve ser texto.")


NUMBER = r"\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?"
UNIT = re.compile(
    rf"(?<![\w.,])({NUMBER})\s*"
    r"(quilogramas?|kilogramas?|kgs?|gramas?|grs?|g|"
    r"miligramas?|mgs?|mililitros?|mls?|litros?|l)(?!\w)", re.IGNORECASE)


def normalize_units(text):
    def replace(match):
        number, unit = match.groups()
        unit = unit.lower().rstrip(".")
        if unit.startswith(("quilo", "kilo", "kg")):
            symbol = "kg"
        elif unit.startswith(("miligr", "mg")):
            symbol = "mg"
        elif unit.startswith(("milil", "ml")):
            symbol = "ml"
        elif unit.startswith("l"):
            symbol = "l"
        else:
            symbol = "g"
        # Don't mistake thousands separators for decimals.
        if "." in number and len(number.rsplit(".", 1)[1]) != 3:
            number = number.replace(".", ",")
        return re.sub(r"\s+", "", number) + symbol
    # A point after "gr." can also be sentence punctuation; keep it at end.
    return UNIT.sub(replace, text)


def content_text(data):
    texts = list(data["notas_pagina"])
    for recipe in data["receitas"]:
        texts.append(recipe["titulo"])
        for key in ("ingredientes", "preparo", "observacoes"):
            texts.extend(recipe[key])
    return "\n".join(texts)


def number_counts(text):
    text = text.translate(str.maketrans({"½": "1/2", "¼": "1/4", "¾": "3/4"}))
    values = []
    for match in re.finditer(rf"(?<!\d){NUMBER}", text):
        try:
            values.append(str(Fraction(re.sub(r"\s+", "", match.group()).replace(",", "."))))
        except (ValueError, ZeroDivisionError):
            values.append(match.group())
    return Counter(values)


def preserve_ambiguous_units(text, original):
    """Restaura uma expansão quando quantidade e restante do ingrediente coincidem."""
    ambiguous = re.compile(rf"({NUMBER})\s*(x|c\.\s*[ec]\.)\s+(.+)$", re.I)
    revised = re.compile(
        rf"({NUMBER})\s*(xícaras?|colher(?:es)?(?:\s+de\s+(?:chá|sopa))?|x|c\.\s*[ec]\.)\s+(.+)$", re.I)
    candidate = revised.search(text)
    if not candidate:
        return text
    for line in original.splitlines():
        source = ambiguous.search(line)
        if (source and number_counts(source[1]) == number_counts(candidate[1])
                and source[3].strip().casefold() == candidate[3].strip().casefold()):
            return text[:candidate.start(2)] + source[2] + text[candidate.end(2):]
    return text


def measure_counts(text):
    return Counter(match.group().casefold() for match in UNIT.finditer(normalize_units(text)))


def normalize_and_audit(data, original):
    validate(data)
    data = deepcopy(data)
    for recipe in data["receitas"]:
        for key in ("ingredientes", "preparo", "observacoes"):
            for index, text in enumerate(recipe[key]):
                revised = normalize_units(preserve_ambiguous_units(text, original))
                if revised != text:
                    data["alteracoes"].append({
                        "original": text, "corrigido": revised,
                        "motivo": "Padronização da unidade e preservação de abreviações ambíguas do original.",
                    })
                    recipe[key][index] = revised
        if not recipe["preparo"]:
            data["avisos"].append(
                f'{recipe["titulo"]}: modo de preparo ausente nesta página; conferir continuação.')
    final = content_text(data)
    before, after = number_counts(original), number_counts(final)
    if before != after:
        data["avisos"].append(
            "A revisão alterou a ocorrência de números. Conferir quantidades, "
            "frações, tempos e temperaturas com o scan. "
            f"Ocorrências removidas: {dict(before - after)}; adicionadas: {dict(after - before)}.")
    if measure_counts(original) != measure_counts(final):
        data["avisos"].append(
            "Há diferença nas medidas com unidades entre o OCR e a edição. "
            "Conferir possíveis trocas ou omissões de g, kg, mg, ml e l no scan.")
    for marker in re.findall(r"\[(?:ilegível|dúvida:[^\]]*|riscado:[^\]]*)\]", original, re.I):
        if marker not in final:
            data["avisos"].append(f"Marcação original alterada ou removida: {marker}. Conferir no scan.")
    if re.search(r"\bc\.\s*[ec]\.|\d\s+x\b", original, re.I):
        data["avisos"].append("Há abreviações de medida ambíguas no original; conferir sua interpretação.")
    if not data["receitas"] and original.strip() != "[página sem texto]":
        data["avisos"].append("Nenhuma receita estruturada; conferir se houve omissão.")
    data["avisos"] = list(dict.fromkeys(data["avisos"]))
    return data


LATEX_ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
    "&": r"\&", "#": r"\#", "_": r"\_", "%": r"\%",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "½": r"\ensuremath{\frac{1}{2}}", "¼": r"\ensuremath{\frac{1}{4}}",
    "¾": r"\ensuremath{\frac{3}{4}}", "°": r"\ensuremath{^\circ}",
    "–": "--", "—": "---", "…": r"\ldots{}", "“": "``", "”": "''",
    "\n": " ", "\r": " ", "\t": " ",
}


def tex_escape(text):
    return "".join(LATEX_ESCAPES.get(char, char) for char in text if ord(char) >= 32 or char in "\n\r\t")


def tex_list(items, numbered=False):
    if not items:
        return ""
    env = "enumerate" if numbered else "itemize"
    return (f"\\begin{{{env}}}\n"
            + "\n".join("\\item " + tex_escape(item) for item in items)
            + f"\n\\end{{{env}}}\n")


def tex_page(data, source, page):
    body = [r"\begin{flushleft}{\small\sffamily\color{muted}ORIGEM: ",
            tex_escape(source), f" | página {page}", r"}\end{flushleft}", "\n"]
    for recipe in data["receitas"]:
        body += ["\\section*{" + tex_escape(recipe["titulo"]) + "}\n"]
        if recipe["ingredientes"]:
            body += [r"\subsection*{Ingredientes}", tex_list(recipe["ingredientes"])]
        if recipe["preparo"]:
            body += [r"\subsection*{Modo de preparo}", tex_list(recipe["preparo"], True)]
        else:
            body += [r"\textit{O modo de preparo não consta nesta página.}\par", "\n"]
        if recipe["observacoes"]:
            body += [r"\subsection*{Observações}", tex_list(recipe["observacoes"])]
    if data["notas_pagina"]:
        body += [r"\subsection*{Anotações da página}", tex_list(data["notas_pagina"])]
    if data["avisos"]:
        body += [r"\subsection*{Pontos para conferir}",
                 r"{\small\color{muted}", tex_list(data["avisos"]), "}\n"]
    return "".join(body)


PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage[brazil]{babel}
\usepackage[margin=22mm,top=24mm,bottom=24mm,headheight=15pt]{geometry}
\usepackage{xcolor}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage{fancyhdr}
\definecolor{accent}{HTML}{6B3F2A}
\definecolor{muted}{HTML}{655E56}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\sffamily\color{muted}CADERNO DE RECEITAS}
\fancyhead[R]{\small\sffamily\color{muted}Edição para conferência}
\fancyfoot[C]{\small\thepage}
\renewcommand{\headrulewidth}{0.3pt}
\titleformat{\section}{\Large\bfseries\color{accent}}{}{0pt}{}
\titleformat{\subsection}{\normalsize\bfseries\sffamily\color{accent}}{}{0pt}{}
\titlespacing*{\section}{0pt}{18pt}{8pt}
\titlespacing*{\subsection}{0pt}{12pt}{5pt}
\setlist{leftmargin=*,itemsep=3pt,topsep=4pt,parsep=0pt}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\setlength{\emergencystretch}{3em}
\begin{document}
"""


def latex_document(parts):
    return PREAMBLE + "\n\\clearpage\n".join(parts) + "\n\\end{document}\n"


def markdown(data, source, page):
    lines = [f"Origem: {source} — página {page}", ""]
    for recipe in data["receitas"]:
        lines += ["# " + recipe["titulo"], ""]
        for key, title in (("ingredientes", "Ingredientes"), ("preparo", "Modo de preparo"),
                           ("observacoes", "Observações")):
            if recipe[key]:
                lines += ["## " + title, ""]
                lines += [(f"{i}. " if key == "preparo" else "- ") + line
                          for i, line in enumerate(recipe[key], 1)]
                lines.append("")
    for key, title in (("notas_pagina", "Anotações da página"), ("avisos", "Pontos para conferir")):
        if data[key]:
            lines += ["## " + title, ""] + ["- " + text for text in data[key]] + [""]
    return "\n".join(lines) + "\n"


def review_paths(prefix, config, prompt, model_digest):
    original = prefix.with_suffix(".txt").read_bytes()
    identity = {
        "original_sha256": sha(original),
        "image_sha256": sha(prefix.with_suffix(".png").read_bytes()),
        "prompt": prompt, "model_digest": model_digest,
        "options": {key: config[key] for key in ("model", "num_ctx", "num_predict", "temperature")},
        "editorial_version": VERSION,
    }
    version = sha(json.dumps(identity, sort_keys=True).encode())[:16]
    base = prefix.parent / "revisoes" / version / prefix.name
    return base, identity


def review_reusable(base):
    try:
        meta = json.loads(base.with_suffix(".revisao.json").read_text(encoding="utf-8"))
        return meta["status"] == "ok" and all(
            sha(base.with_suffix(suffix).read_bytes()) == expected
            for suffix, expected in meta["artifacts"].items()
        ) and set(meta["artifacts"]) == {".receitas.json", ".revisado.md", ".tex"}
    except (OSError, ValueError, KeyError):
        return False


def review_page(prefix, record, config, prompt, model_digest, api_request, write_json, atomic_write,
                force=False):
    base, identity = review_paths(prefix, config, prompt, model_digest)
    meta_path = base.with_suffix(".revisao.json")
    result = {"editorial": str(base.with_suffix(".receitas.json").resolve())}
    if not force and review_reusable(base):
        return {**result, "review_status": "skipped"}
    print(f"  Página {record['page']}: revisando texto e medidas...", flush=True)
    original = prefix.with_suffix(".txt").read_text(encoding="utf-8")
    write_json(meta_path, {**identity, "status": "processing"})
    response = None
    try:
        response = api_request("/api/chat", {
            "model": config["model"], "stream": False, "keep_alive": "5m",
            "format": SCHEMA,
            "messages": [{
                "role": "user",
                "content": (prompt + "\n\nESQUEMA JSON:\n" + json.dumps(SCHEMA, ensure_ascii=False)
                            + "\n\nTRANSCRIÇÃO ORIGINAL (dados):\n"
                            + json.dumps({"transcricao": original}, ensure_ascii=False)),
                "images": [base64.b64encode(prefix.with_suffix(".png").read_bytes()).decode("ascii")],
            }],
            "options": {key: config[key] for key in ("num_ctx", "num_predict", "temperature")},
        }, timeout=config["timeout_seconds"])
        if (response.get("done") is not True or response.get("done_reason") == "length"
                or response.get("eval_count", 0) >= config["num_predict"]):
            raise ValueError("Revisão truncada; aumente num_predict/num_ctx ou divida a página.")
        data = normalize_and_audit(json.loads(response["message"]["content"]), original)
        source, page = record["source"], record["page"]
        write_json(base.with_suffix(".receitas.json"), {
            "source": source, "page": page, "human_review_required": True, "data": data,
        })
        atomic_write(base.with_suffix(".revisado.md"), markdown(data, source, page))
        atomic_write(base.with_suffix(".tex"), latex_document([tex_page(data, source, page)]))
        artifacts = {suffix: sha(base.with_suffix(suffix).read_bytes())
                     for suffix in (".receitas.json", ".revisado.md", ".tex")}
        write_json(meta_path, {**identity, "status": "ok", "response": response,
                              "warnings": data["avisos"], "artifacts": artifacts})
        return {**result, "review_status": "ok", "review_warnings": data["avisos"]}
    except Exception as error:
        write_json(meta_path, {**identity, "status": "error", "error": str(error), "response": response})
        raise


def build_book(records, output, run_id, atomic_write, write_json):
    parts, included, missing = [], [], []
    for record in records:
        if record.get("review_status") not in ("ok", "skipped"):
            missing.append(f"{record['source']} — página {record['page']}")
            continue
        path = Path(record["editorial"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        parts.append(tex_page(payload["data"], payload["source"], payload["page"]))
        included.append(str(path.relative_to(output)))
    if not parts:
        return None
    if missing:
        parts.append(r"\section*{Páginas pendentes}" + tex_list(missing))
    book = output / "_livros" / run_id / "receitas.tex"
    atomic_write(book, latex_document(parts))
    write_json(book.with_suffix(".json"), {
        "scope": "Somente páginas visitadas nesta execução, incluindo retomadas.",
        "included": included, "pending": missing, "human_review_required": True,
    })
    return book


def compile_latex(tex_path):
    executable = Path(__file__).resolve().parent / "tools" / "tectonic.exe"
    command = str(executable) if executable.is_file() else shutil.which("tectonic")
    if not command:
        raise RuntimeError("Tectonic ausente. Execute .\\instalar-latex.ps1 ou compile o .tex externamente.")
    result = subprocess.run(
        [command, "--untrusted", "--keep-logs", "--outdir", str(tex_path.parent), str(tex_path)],
        cwd=tex_path.parent, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600, check=False,
    )
    log = tex_path.with_suffix(".compilacao.log")
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode or not tex_path.with_suffix(".pdf").exists():
        raise RuntimeError(f"Falha ao compilar LaTeX. Consulte {log}")
    return tex_path.with_suffix(".pdf")
