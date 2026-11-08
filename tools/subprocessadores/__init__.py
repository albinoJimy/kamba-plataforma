"""Inventario de subprocessadores e documentos gerados dele (KAM-069).

Tres modulos:

    inventario.py   le e valida o `gov/subprocessadores.yaml`, e deriva a versao
    documentos.py   gera a lista publica e o mapa de tratamentos
    cli.py          escreve, verifica (`--check`) ou imprime a versao

O `__init__` fica vazio de logica de proposito: o `kamba_yaml` que o
`inventario` usa e o unico `import` desta arvore, e um `__init__` que importasse
os tres modulos punha o custo de os carregar em quem so quer a versao.
"""
