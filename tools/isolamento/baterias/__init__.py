"""As baterias X-01..X-11, C-01 e P-01. Um modulo por bateria.

Cada modulo **declara** os seus casos com `registar_caso` ao ser importado e
nao executa nada: o `fn` corre quando o corredor lhe chama, com o `Contexto`
que a suite construiu. E isso que permite a cobertura ser medida a seco, sem
PostgreSQL e sem `node`.

Para acrescentar um caso, ver `tools/isolamento/README.md`.
"""

from __future__ import annotations

#: Os modulos por importar, pela ordem das baterias. Uma lista e nao uma
#: varredura do directorio: um modulo novo entra aqui de proposito, e um
#: ficheiro deixado a meio nao passa a correr sozinho.
MODULOS = (
    "x01_rotas",
    "x02_tools",
    "x03_x04_x05_base",
    "x06_vectores",
    "c01_contacto",
    "p01_pooling",
    "evt_consumidores",
    "jobs_filas",
)

_carregado = False


def carregar() -> None:
    """Importa os modulos de bateria uma vez. Idempotente."""
    global _carregado  # noqa: PLW0603 — um registo global tem um sinalizador global
    if _carregado:
        return
    from importlib import import_module

    for modulo in MODULOS:
        import_module(f"{__name__}.{modulo}")
    _carregado = True
