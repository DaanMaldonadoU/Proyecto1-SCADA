# -*- coding: utf-8 -*-
"""
gateway — proceso que habla con la planta (SIM, EMULATE o REAL) y publica por ZeroMQ.

Se ejecuta con `python -m gateway --modo SIM|EMULATE|REAL`. SIM corre en cualquier
Python 3.12+; EMULATE y REAL necesitan Windows, Python de 32 bits, pywin32 y OpenOPC.
"""
