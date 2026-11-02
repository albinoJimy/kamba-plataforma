# infra/modules/provider-pendente — a costura do fornecedor, a falhar fechado.
#
# ESTE MODULO NAO PROVISIONA NADA, E ISSO E A ENTREGA.
#
# O KAM-075 manda infraestrutura «agnostica de fornecedor» porque a **D1** — o
# alojamento, Luanda ou JNB/CPT — e decisao do fundador e esta `em branco`:
# linha A1 de `docs/tecnica/evidencia/validacao/GoLive_Gate.md`, dependente de
# >= 3 cotacoes das quais nenhuma foi pedida (KAM-105).
#
# Havia duas maneiras de escrever isto. A primeira era deixar `infra/modules/`
# vazio e escrever num README que o fornecedor falta. A segunda e esta: por a
# decisao em falta no caminho de execucao, para que um `tofu apply` **pare
# nela** em vez de a adivinhar. A diferenca aparece no unico momento que conta —
# quando alguem tentar aplicar isto sem a D1.
#
# Nao ha bloco `provider` nem `resource` aqui, e tambem nao ha nos outros
# modulos nem nos ambientes. E por isso que `tofu init -backend=false` e
# `tofu validate` correm sem rede nesta arvore.

terraform {
  required_version = "1.10.6"
}

locals {
  # As variaveis entram em `locals` para que o `validate` as veja usadas: uma
  # interface declarada e nunca referida e uma interface que ninguem verifica.
  forma = "${var.vcpu}vcpu-${var.memoria_gb}gb"

  pedido = {
    ambiente   = var.ambiente
    forma      = local.forma
    disco_gb   = var.disco_gb
    dns_ttl    = var.dns_ttl_segundos
    etiquetas  = var.etiquetas
    cloud_init = var.cloud_init
  }
}
