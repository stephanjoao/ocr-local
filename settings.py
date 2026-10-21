"""Configuração compartilhada pela interface e pelos comandos."""
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parent
BATCHES = ROOT / 'outputs' / 'lotes'


def validate_config(config):
    value = dict(config)
    if not isinstance(value.get('model'), str) or not value['model'].strip():
        raise ValueError('Informe o nome do modelo local.')
    value['model'] = value['model'].strip()
    for field in ('num_ctx', 'num_predict', 'max_image_side', 'pdf_dpi', 'timeout_seconds'):
        if type(value.get(field)) is not int or value[field] <= 0:
            raise ValueError(f'{field} deve ser um inteiro maior que zero.')
    if value['num_predict'] >= value['num_ctx']:
        raise ValueError('num_predict deve ser menor que num_ctx, reservando espaço à imagem.')
    temperature = value.get('temperature')
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError('temperature deve ser um número entre 0 e 2.')
    if type(value.get('review_enabled', True)) is not bool:
        raise ValueError('review_enabled deve ser true ou false.')
    return value


def load_config(path=None):
    return validate_config(json.loads((Path(path) if path else ROOT / 'config.json').read_text(encoding='utf-8-sig')))


def read_prompt(name):
    text = (ROOT / name).read_text(encoding='utf-8-sig').strip()
    if not text:
        raise ValueError(f'O arquivo {name} está vazio.')
    return text
