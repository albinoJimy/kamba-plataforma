# Versoes fixadas (DoD do KAM-075: «Dependencias de IaC fixadas por
# versao/hash; licencas permitidas»).
#
# `required_version` e EXACTO e nao uma gama. Uma gama (`~> 1.10`) deixaria a
# versao do CI divergir da de quem desenvolve, e e disso que vive um «aqui
# funciona».
#
# Medido: `tofu version` na imagem `ghcr.io/opentofu/opentofu:1.10.6` devolve
# `OpenTofu v1.10.6` (2026-11-02).
#
# `required_providers` esta VAZIO, e nao esquecido: nao ha fornecedor ate a D1
# fechar (ADR-L007 §5). E por isso que `tofu init -backend=false` e
# `tofu validate` correm sem rede nesta arvore.
terraform {
  required_version = "1.10.6"

  required_providers {}
}
