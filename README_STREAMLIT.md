=== COMO RODAR O STREAMLIT ===

1. ABRA UM NOVO TERMINAL/POWERSHIELD OU CMD E DIGITE ESTE COMANDO:

   streamlit run app_streamlit.py
   
   ou se preferir usar python.exe diretamente:

   python.exe -m streamlit run app_streamlit.py


2. A APLICAÇÃO VAI SE INICIAR EM:
   http://localhost:8501


3. NO STREAMLIT, VOCÊ VÁ VER:
   
   [SIDEBAR (ESQUERDA)]
   - Modelos do Ollama disponíveis
   - Configurações ajustáveis
   
   [PÁGINA PRINCIPAL]
   - Pasta scans: lista os arquivos (imagens/PDFs)
   - Botões rápidos: Gerar Resumo, Estatísticas


4. COLOQUE SEUS ARQUIVOS NA PASTA:
   
   C:\Users\joaos\Documents\Projects\ocr-local\scans
   
   Formatos suportados: JPG, PNG, TIFF, PDF


5. PARA ADICIONAR CONFIGURAÇÕES CUSTOMIZADAS:
   
   Edite o arquivo: config.json
   
   No diretório raiz do projeto.

=== FIM ===