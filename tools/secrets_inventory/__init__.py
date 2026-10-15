"""Verificador do inventario de segredos da KAMBÁ (KAM-010).

Sem dependencias externas, pela razao do KAM-001: as ferramentas que correm nos
*hooks* e no CI tem de funcionar num clone antes de qualquer instalacao. O YAML
e lido por `yamlsubset`, que aceita exactamente a forma de
`ops/secrets-inventory.yaml` e recusa o resto.
"""
