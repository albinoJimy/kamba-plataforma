"""Negativa: o mesmo com a configuracao explicita do uvicorn."""

import uvicorn

configuracao = uvicorn.Config("kamba_agr.app:app", log_config={"version": 1})
