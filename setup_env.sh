#!/bin/bash
# Setup environment for Caderno de receitas project
export PYTHONPATH="/home/stephan/Documents/Projects/ocr-local:$PYTHONPATH"
echo "PYTHONPATH set to: $PYTHONPATH"
source venv/bin/activate 2>/dev/null || echo 'No virtualenv found'
echo "Ready to run: ./caderno"
