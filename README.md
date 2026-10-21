# Caderno de receitas

Transforma imagens e PDFs de um caderno em um livro de receitas usando o Ollama
local. O fluxo é **ler → responder às dúvidas → gerar PDF**. O programa não gera
o PDF automaticamente durante a leitura ou quando você responde a uma pergunta.

## Começar

Com as dependências instaladas, abra a interface:

```bash
./caderno
```

Acesse **http://localhost:8501**. Para outra porta: `./caderno abrir --porta 8502`.
O Ollama precisa estar ativo com o modelo definido em `config.json`:

```bash
ollama pull qwen3-vl:8b-instruct
./caderno verificar
```

Para preparar um ambiente novo (Python 3.11 ou superior):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Se o ambiente virtual não tiver pip, mas o Python do sistema tiver:

```bash
python3 -m pip --python .venv/bin/python install -r requirements.txt
```

No Windows, use `preparar.ps1` e depois `caderno.ps1`. Os comandos são os mesmos:
`./caderno verificar` no Linux corresponde a `.\caderno.ps1 verificar` no PowerShell.

## Na interface

1. **Envie várias páginas à esquerda.** JPG, JPEG, PNG, WebP, BMP, TIFF multipágina
   e PDF são aceitos. A ordem da seleção é preservada. Clique em **Ler páginas**.
2. **Acompanhe a leitura no topo.** A etapa, o nome do arquivo e o número da página
   aparecem separados da barra. O progresso conta páginas e etapas, não tempo estimado.
3. **Confira a sequência.** Depois da leitura, o modelo procura continuações e
   indícios de páginas fora de ordem. Em **Sequência**, veja a proposta e seus
   motivos. Aceite, mantenha a ordem enviada ou mova/una trechos manualmente.
   As junções preservam os textos e todas as páginas de origem.
4. **Responda às dúvidas.** O original aparece à direita. Você pode corrigir um
   trecho, manter a incerteza com aviso ou confirmar que conferiu o original.
   Repetições exatas e abreviações são agrupadas com suas páginas de origem.
5. **Revise as receitas.** Em **Receitas**, edite título, ingredientes, preparo e
   observações; também é possível retirar uma receita do livro. Salve cada edição
   antes de trocar de receita ou de formulário.
6. **Gere o PDF.** Depois das respostas e da decisão sobre a sequência, confirme a conferência e clique em
   **Gerar PDF**. O livro aparece à direita, com navegação por página e download.

Cada receita começa em uma nova folha. Receitas longas continuam nas seguintes,
sem reduzir o texto até ficar ilegível. Continuações entre scans só são unidas
depois da confirmação. A análise usa grupos sobrepostos e compara títulos
relacionados distantes; trechos sem título muito afastados podem precisar de
ligação manual. A ordem enviada prevalece quando não há evidência suficiente.
Os textos classificados como alheios às receitas ficam
em **Conteúdo separado das receitas** e nos registros, fora do PDF.

Alterar uma resposta ou receita invalida a prévia anterior. As versões do PDF
continuam no disco; gere novamente para incluir as últimas mudanças.

## No terminal

```bash
./caderno                         # abre a interface
./caderno verificar               # verifica Ollama e modelo
./caderno ler                     # lê a pasta scans/
./caderno ler pagina1.jpg livro.pdf
./caderno conferir                # responde às dúvidas do último lote
./caderno pdf                     # pede confirmação e gera o livro
./caderno listar                  # mostra os lotes salvos
./caderno retomar                 # retoma leitura interrompida
```

`conferir`, `pdf` e `retomar` aceitam um ID de lote ou sua pasta. Exemplo:
`./caderno conferir 20261021-180000-abcd1234`.

Para uso sem terminal interativo, `./caderno pdf <lote> --confirmar` declara que
você conferiu as receitas, mas **não ignora dúvidas pendentes**. Se houver páginas
com falha, a geração exige também `--parcial`. Na interface existe uma opção
equivalente. Não são feitas substituições silenciosas de quantidades ou unidades.

## Dados e retomada

Tudo é salvo em `outputs/lotes/<id>/`:

```text
lote.json                  # estado, respostas, correções e histórico
originais/                 # cópias dos uploads, sem alterar os arquivos de origem
processamento/             # transcrição, imagem de trabalho e revisão por página
receitas-v*.pdf             # versões geradas depois da conferência
```

Reabra um lote em **Trabalhos salvos** ou continue pelo terminal. A retomada
aproveita OCR e revisões íntegros. Respostas e receitas editadas são preservadas.
Os prompts e a configuração usados ficam registrados no lote; novas configurações
valem para novos trabalhos. Mudança do modelo instalado exige um novo lote.

A leitura é sequencial. Mantenha a aba aberta enquanto ela roda. Se houver
interrupção, retome o lote salvo. Após uma parada abrupta do processo, uma trava
`.processing.lock` pode exigir remoção manual, somente se não houver leitura ativa.

Scans são enviados exclusivamente à API local `127.0.0.1:11434`. O download inicial
das dependências e do modelo precisa de internet; a geração de PDF usa fontes
incluídas na biblioteca e não depende de LaTeX nem de serviço externo.

## Configuração e organização

- `settings.py`: validação central da configuração e leitura dos prompts.
- `ocr.py`: imagens, PDFs, API do Ollama, transcrição e retomada por integridade.
- `editorial.py`: revisão visual estruturada, auditoria de medidas e exportação LaTeX legada.
- `studio.py`: dúvidas recorrentes, substituições literais e composição do PDF.
- `ordering.py`: análise de sequência, validação de ligações e composição de continuações.
- `workflow.py`: lotes persistentes e regras de leitura, conferência e geração.
- `app_streamlit.py`: interface, formulários e prévia renderizada do PDF.
- `caderno.py`: comandos que usam o mesmo fluxo da interface.
- `prompt.txt`: transcrição literal, incluindo textos alheios às receitas.
- `prompt_revisao.txt`: seleção de receitas, revisão conservadora e perguntas.
- `prompt_ordenacao.txt`: indícios para conectar e ordenar trechos sem inventar conteúdo.

O modelo pode errar a classificação e a leitura, especialmente em manuscritos.
Uma resposta “não sei” preserva o aviso no PDF. Conferência humana é necessária
para quantidades, frações e abreviações; as respostas não treinam o modelo.

O comando antigo `python ocr.py` e `rodar.ps1` continuam disponíveis para operações
avançadas por página e LaTeX. Esse fluxo não tem o questionário interativo; veja
[CLI avançado](docs/CLI_AVANCADO.md). Prefira `caderno` para o fluxo com conferência.

## Verificação

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/smoke_local.py   # opcional: usa o Ollama e uma imagem sintética
```

Os testes automatizados cobrem persistência, retomada, formulário de respostas,
bloqueio de geração antes da conferência, PDF parcial, correções, paginação,
escape de texto e preservação dos originais. O teste real não mede precisão em cursiva.
