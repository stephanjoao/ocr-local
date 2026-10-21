"""Teste opcional da análise de sequência no Ollama local, com trechos sintéticos."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ocr
import ordering
from settings import load_config, read_prompt


def main():
    recipes = [
        {'id': 'fim', 'titulo': 'Bolo de milho (continuação)', 'source': 'folha-2.png',
         'ingredientes': [], 'preparo': ['3. Despeje a massa de milho na forma.', '4. Asse por 35 minutos.'],
         'observacoes': ['Continuação do Bolo de milho da folha 1.']},
        {'id': 'outra', 'titulo': 'Arroz simples', 'source': 'arroz.png',
         'ingredientes': ['1 xícara de arroz', '2 xícaras de água'],
         'preparo': ['Cozinhe o arroz na água até secar.'], 'observacoes': []},
        {'id': 'inicio', 'titulo': 'Bolo de milho', 'source': 'folha-1.png',
         'ingredientes': ['2 ovos', '1 xícara de milho', '200ml de leite'],
         'preparo': ['1. Bata os ingredientes.', '2. Unte a forma.'],
         'observacoes': ['Continua na folha 2.']},
    ]
    result = ordering.suggest(recipes, load_config(), read_prompt('prompt_ordenacao.txt'), ocr.api_request)
    print(result)
    assert ['inicio', 'fim'] in result['groups'], 'O modelo não identificou a continuação explícita.'
    assert ['outra'] in result['groups'], 'O modelo associou uma receita alheia à continuação.'
    print('Sequência invertida identificada; receita alheia preservada.')


if __name__ == '__main__':
    main()
