# -*- coding: utf-8 -*-
"""tests/conftest.py — añade la raíz del repositorio a sys.path para importar core/ y gateway/."""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
