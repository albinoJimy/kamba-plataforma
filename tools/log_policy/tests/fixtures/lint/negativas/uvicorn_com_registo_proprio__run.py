"""Negativa: sem `log_config=None` o uvicorn escreve texto livre ao lado do logger."""

import uvicorn


def arrancar():
    uvicorn.run("kamba_agr.app:app", host="127.0.0.1", port=8000, access_log=False)
