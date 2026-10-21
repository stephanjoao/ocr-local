from __future__ import annotations
import json
from pathlib import Path
import subprocess
import streamlit as st

ROOT = Path(__file__).resolve().parent


def load_config(filepath='config.json'):
    """Carrega configurações do arquivo JSON ou usa defaults."""
    default_config = {
        "model": "qwen3-vl:8b-instruct",
        "num_ctx": 8192,
        "num_predict": 4096,
        "temperature": 0,
        "max_image_side": 2000,
    }
    if Path(filepath).exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return default_config.copy()


@st.cache_data
def get_ollama_status():
    """Verifica o status do Ollama e lista modelos disponíveis."""
    try:
        result = subprocess.run(
            ['ollama', 'list'], 
            capture_output=True, 
            text=True,
            cwd=str(ROOT)
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')[1:]
            models = []
            for line in lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        models.append(parts[0])
            has_vision = any('vision' in m.lower() for m in models)
            return {'status': 'online', 'models': models, 'has_vision_model': has_vision}
        else:
            return {'status': 'offline', 'error': result.stderr, 'models': []}
    except FileNotFoundError:
        return {'status': 'offline', 'error': 'Ollama não encontrado no PATH', 'models': []}
    except Exception as e:
        return {'status': 'offline', 'error': str(e), 'models': []}


def main():
    st.set_page_config(page_title="OCR Local - Interface Streamlit", layout="wide")
    
    st.title("📄 OCR Local - Interface Streamlit")
    
    with st.sidebar:
        st.header("⚙️ Configurações")
        config = load_config()
        model = st.text_input("Modelo", value=config.get("model", "qwen3-vl:8b-instruct"))
        num_ctx = st.slider("Context Window (tokens)", 1024, 32768, config.get("num_ctx", 8192))
        num_predict = st.slider("Max Tokens de Resposta", 512, 8192, config.get("num_predict", 4096))
        max_image_side = st.slider("Lado Máximo da Imagem (pixels)", 256, 4096, 256, config.get("max_image_side", 2000))
        
        ollama_status = get_ollama_status()
        if ollama_status['status'] == 'online':
            st.success("✅ Ollama online!")
            for m in ollama_status['models']:
                st.write(f"- `{m}`")
        else:
            st.error(f"❌ Ollama offline: {ollama_status.get('error')}")

    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.header("📂 Arquivos Disponíveis")
        scans_dir = ROOT / "scans"
        
        if not scans_dir.exists():
            st.info("Crie a pasta 'scans' e adicione seus arquivos (imagens ou PDFs).")
        else:
            files_list = list(scans_dir.rglob('*.[jJpP][gGxXzZ]|[iI][tT][tT]|[pPnN[gG]]|[Pp][dD][fF]'))
            
            if not files_list:
                st.info("Nenhum arquivo encontrado em 'scans'.")
            else:
                st.success(f"✅ {len(files_list)} arquivo(s) encontrados!")

    with col2:
        st.header("🚀 Ações Rápidas")
        c1, c2 = st.columns(2)
        
        with c1:
            if st.button("📋 Gerar Resumo", use_container_width=True):
                import glob
                outputs_dir = ROOT / "outputs"
                json_files = sorted(outputs_dir.glob("**/*.json")) if (ROOT / "outputs").exists() else []
                
                results = {}
                for jf in json_files:
                    try:
                        with open(jf, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        versions = data.get('results', {}).keys()
                        if versions:
                            latest = max(versions)
                            results[str(jf.relative_to(ROOT))] = {'version': latest}
                    except:
                        pass
                
                if results:
                    output_file = ROOT / "outputs" / "resumo.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(results, f, indent=2)
                    st.success(f"✅ Resumo salvo! ({len(results)} arquivos)")

        with c2:
            if st.button("📊 Estatísticas", use_container_width=True):
                outputs_dir = ROOT / "outputs"
                stats_text = f"**Arquivos JSON encontrados:** {len(list(outputs_dir.glob('**/*.json'))) if outputs_dir.exists() else 0}"
                st.text_area("Estatísticas", value=stats_text, height=200)

    st.markdown("---")
    st.caption("🔧 Interface Streamlit para OCR Local")


if __name__ == "__main__":
    main()