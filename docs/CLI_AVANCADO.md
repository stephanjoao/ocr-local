# Fluxo avançado legado

Este documento descreve `ocr.py` e `rodar.ps1`, sem o questionário interativo.
Para o novo fluxo, use [caderno](../README.md). As instruções abaixo devem ser
executadas na raiz do projeto. A exportação LaTeX preserva anotações e avisos;
o livro da interface é composto por ReportLab depois da conferência.

# OCR local do caderno de receitas

Transcreve scans usando **Qwen3-VL 8B Instruct no Ollama**, uma página por vez.
Em seguida, compara a transcrição com a imagem, revisa a redação, padroniza unidades
e organiza as receitas em Markdown, JSON e LaTeX com layout pronto para PDF.
As imagens são enviadas somente à API local `127.0.0.1:11434`; os originais são preservados.
O download das dependências e do modelo precisa de internet. Depois disso, o OCR pode rodar offline.

## Começar no Windows

Abra o PowerShell nesta pasta:

```powershell
cd "$HOME\Documents\Projects\ocr-local"
.\preparar.ps1
.\rodar.ps1 --check
```

O Ollama precisa estar aberto e ter o modelo:

```powershell
ollama pull qwen3-vl:8b-instruct
```

Se `ollama` não estiver no PATH:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3-vl:8b-instruct
```

Coloque seus arquivos em **scans/** (subpastas também são aceitas).
Formatos: JPG, JPEG, PNG, WebP, BMP, TIFF multipágina e PDF.
Arquivos PDF protegidos por senha precisam ser desbloqueados antes.

Teste primeiro algumas páginas:

```powershell
.\rodar.ps1 --limit 3
```

Depois processe o restante:

```powershell
.\rodar.ps1
```

Para gerar também o **PDF diagramado**:

```powershell
.\instalar-latex.ps1
.\rodar.ps1 --compile
```

O instalador usa Tectonic 0.17.0 oficial, valida o SHA256 e instala apenas em
`tools/`, sem alterar o PATH ou instalar uma distribuição TeX global.
A primeira compilação baixa os pacotes e fontes LaTeX necessários. Depois de
armazenados em cache, esse mesmo layout pode ser compilado sem internet.
Os textos das receitas não são enviados a um serviço de compilação.

Para compilar um `.tex` que você editou, sem chamar o modelo:

```powershell
.\rodar.ps1 --compile-tex "caminho\receitas.tex"
```

Se a política do PowerShell bloquear scripts, use diretamente
`.\.venv\Scripts\python.exe ocr.py`. Para preparar sem script:
`python -m venv .venv`, seguido de
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## Resultados

Exemplo de estrutura (o identificador da versão é calculado automaticamente):

```text
scans/
  caderno.pdf
  pagina-solta.jpg
outputs/
  caderno.pdf/
    <versao>/
      pagina-0001.txt
      pagina-0001.png
      pagina-0001.json
      revisoes/
        <versao-editorial>/
          pagina-0001.revisado.md
          pagina-0001.receitas.json
          pagina-0001.revisao.json
          pagina-0001.tex
      pagina-0002.txt
      ...
  pagina-solta.jpg/
    <versao>/
      pagina-0001.txt
      pagina-0001.png
      pagina-0001.json
  _runs/
    <data-hora>.json
  _livros/
    <execucao>/
      receitas.tex
      receitas.json
      receitas.pdf  (com --compile)
```

- `.txt`: transcrição em UTF-8.
- `.png`: imagem efetivamente usada na leitura, para comparação.
- `.json`: origem, número da página, modelo, configuração, resposta original,
  duração, integridade dos arquivos e avisos.
- `_runs`: resumo de cada execução. Falhas não impedem os próximos arquivos.
- `.revisado.md`: versão corrigida, organizada e legível.
- `.receitas.json`: títulos, ingredientes, etapas, notas, avisos e alterações.
- `.revisao.json`: resposta original da revisão, parâmetros e controle de integridade.
- `.tex`: página diagramada, com texto escapado pelo programa; comandos que apareçam
  na receita não são executados como LaTeX.
- `_livros`: compilação das páginas visitadas no lote, na ordem dos nomes dos
  arquivos e das páginas. Com `--limit`, o livro pode ser parcial. Rodar novamente
  sem limite reúne todas as páginas, aproveitando as revisões já concluídas.

Os arquivos individuais são **por página**, podendo conter várias receitas.
Receitas que atravessam páginas não são unidas automaticamente; continuam
identificadas pela origem. Não se inventam etapas faltantes para completá-las.
Os PDFs são renderizados visualmente; não se presume que já tenham uma camada de texto.

## Revisão e padronização

O fluxo padrão tem duas etapas:

1. **OCR literal** com `prompt.txt`: preserva a grafia da página.
2. **Revisão visual e editorial** com `prompt_revisao.txt`: corrige a escrita,
   confere a imagem e organiza os dados. Usa o mesmo modelo local, sequencialmente.

Exemplos de padronização:

| Original | Edição revisada |
| --- | --- |
| `100 grs` | `100g` |
| `90grs` | `90g` |
| `30 gramas` | `30g` |
| `200 ml` | `200ml` |
| `1 kg` | `1kg` |
| `06 uvas` | `6 uvas` |
| `1/2 xícara` | `1/2 xícara` |

A normalização de símbolos inequívocos também é aplicada por regras em código,
além do prompt. Isso não converte quantidades nem adivinha equivalências:
`1 xícara` não vira um peso em gramas. Abreviações ambíguas como `c.e.` e `c.c.`,
quantidades ausentes e trechos ilegíveis devem continuar sinalizados.

A revisão registra alterações propostas e verifica automaticamente diferenças
na ocorrência de números e medidas com unidades. Quando quantidade e restante
do ingrediente coincidem, uma expansão de abreviação ambígua é revertida para
a abreviação original. Essa verificação é um alerta, não prova de correção:
trocas entre ingredientes ou omissões de palavras ainda exigem conferência.

O layout LaTeX usa papel A4, títulos em marrom, listas de ingredientes,
preparo numerado, notas, origem e seção de pontos para conferir. É uma
**edição para conferência**. Revise as receitas antes de tratá-la como edição final.

Para desativar a segunda etapa em uma execução:

```powershell
.\rodar.ps1 --no-review
```

Ou defina `"review_enabled": false` em `config.json`.

## Retomada e versões

Execute novamente o mesmo comando para retomar. Páginas completas com arquivos
íntegros são ignoradas; falhas e respostas truncadas são tentadas novamente.
`--limit` limita as páginas com trabalho pendente, incluindo revisão de OCR antigo,
sem contar páginas com todas as etapas concluídas.
Ctrl+C interrompe o lote; páginas já salvas ficam disponíveis.

Uma mudança no scan, prompt, configuração ou versão do modelo cria outra pasta
de versão, preservando as saídas anteriores. Um PDF alterado gera nova versão para
todas as suas páginas. `--force` reprocessa e substitui as saídas da mesma versão.
Mantenha correções manuais em arquivos separados: editar o `.txt` gerado invalida
sua integridade e faz a próxima execução refazê-lo.

O OCR e a revisão possuem retomadas independentes. Se a revisão falhar, o OCR
completo continua salvo e a próxima execução tenta apenas a revisão. Mudar
`prompt_revisao.txt` gera outra versão editorial sem repetir o OCR. Páginas já
processadas pela primeira versão do projeto também recebem a revisão ao rodar
novamente. Arquivos editoriais gerados são verificados por integridade; mantenha
edições manuais em cópias separadas.

Uma trava impede dois lotes simultâneos na mesma pasta de saída. Após uma interrupção
brusca do computador, remova `outputs/.ocr.lock` somente se não houver lote rodando.

## Ajustes e revisão

Edite `prompt.txt` para mudar o OCR literal, `prompt_revisao.txt` para mudar a
revisão e `config.json` para os parâmetros.
O padrão usa contexto de 8192 tokens, até 4096 tokens de resposta e imagem com lado
maior de até 2000 pixels. São valores iniciais para a RTX 3060 de 12 GB, não uma
garantia de consumo máximo de memória. O primeiro processamento pode ser mais lento.

Guarde scans coloridos de boa qualidade. Não há filtros destrutivos nem alteração
dos originais. A imagem de trabalho é orientada conforme EXIF, recebe fundo branco
se transparente e é reduzida mantendo a proporção. PDFs são renderizados até 200 dpi,
respeitando o limite de pixels.

Se a letra ficar pequena, teste recortes por receita ou aumente `max_image_side`;
isso pode aumentar o uso de memória. Em falta de memória, feche outros programas
que usam GPU ou reduza esse limite. Respostas truncadas ficam como `incomplete`;
aumente `num_predict` e, se necessário, `num_ctx`, ou divida a página em recortes.

**Toda transcrição exige revisão humana**, especialmente números, frações,
ingredientes, tempos e temperaturas. `status: ok` significa execução concluída,
não precisão verificada. O modelo pode inventar leituras sem marcar dúvida;
os avisos não são uma pontuação de confiança.

Não há treinamento automático com suas correções.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Para verificar também uma transcrição real no Ollama (usa a GPU e uma receita
impressa sintética, sem tocar nas pastas de scans e resultados):

```powershell
.\.venv\Scripts\python.exe -X utf8 tests\smoke_local.py
```

Os testes cobrem OCR, retomada independente da revisão, falhas, medidas,
preservação do original, estrutura JSON e escape de conteúdo para LaTeX.
A precisão em manuscritos depende da legibilidade e exige avaliação com scans
representativos do caderno.

Documentação usada: [visão no Ollama](https://docs.ollama.com/capabilities/vision),
[API de chat](https://docs.ollama.com/api/chat) e
[modelo](https://ollama.com/library/qwen3-vl:8b-instruct),
[saídas estruturadas](https://docs.ollama.com/capabilities/structured-outputs) e
[compilador Tectonic](https://tectonic-typesetting.github.io/en-US/install.html).
