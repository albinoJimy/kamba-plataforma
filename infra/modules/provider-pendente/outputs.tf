# AS SAIDAS QUE A INTERFACE PROMETE, e a barreira que impede um `apply`.
#
# Cada saida leva DUAS precondicoes, e sao duas porque ha duas coisas em falta:
#
#   1. a decisao D1 (que fornecedor, que regiao) — acto do fundador;
#   2. um modulo que a implemente — nao existe nenhum.
#
# Uma precondicao de saida avalia-se no `plan` e no `apply`, e **nao** no
# `validate`. Isso da exactamente o comportamento que se quer:
#
#   tofu validate   passa  (a estrutura verifica-se hoje, sem rede e sem conta)
#   tofu plan       PARA   (as duas coisas acima nao existem)
#
# Era essa a escolha. Um `validate` vermelho tornaria o gate 2 inutil para
# estes ficheiros, e verificar a estrutura antes da D1 e metade do valor deste
# ticket.
#
# NOTA SOBRE A FORMA DESTAS CONDICOES, porque a primeira versao estava errada e
# foi o proprio validador que a corrigiu: escrevia-se `condition = false`, e o
# OpenTofu 1.10.6 recusa-o — «The condition expression must refer to at least
# one object from elsewhere in the configuration, or else its result would not
# be checking anything». O argumento e bom e ficou: uma barreira tem de ser uma
# afirmacao sobre alguma coisa, nao um literal.

locals {
  razao_d1 = join(" ", [
    "A D1 — alojamento, Luanda ou JNB/CPT — nao esta decidida, e nenhum recurso",
    "se cria sem ela. E acto do fundador: linha A1 de",
    "docs/tecnica/evidencia/validacao/GoLive_Gate.md, dependente de >= 3",
    "cotacoes das quais nenhuma foi pedida (KAM-105).",
    "Decidida a D1, a sua referencia entra em `dados.decisao_d1` do env.yaml.",
  ])

  razao_costura = join(" ", [
    "Este modulo e a costura, nao um fornecedor: nao implementa nenhum e por",
    "isso nao cria nada. Para aplicar: escreve-se",
    "infra/modules/provider-<nome>/ com estas variaveis e estas saidas, e",
    "troca-se a linha `source` em infra/envs/<ambiente>/main.tf.",
    "Ver infra/modules/README.md.",
  ])
}

output "endereco_ipv4" {
  description = "Endereco publico do host. Nunca chega a existir neste modulo."
  value       = null

  precondition {
    condition     = var.decisao_d1 != null
    error_message = local.razao_d1
  }

  precondition {
    condition     = var.fornecedor_implementado
    error_message = local.razao_costura
  }
}

output "identidade_para_o_ci" {
  description = <<-EOT
    A identidade federada com que o CI se autentica — OIDC, nao chave estatica
    (ADR-L007 §4a). O nome dela e do fornecedor; a interface so promete que
    existe uma e que nao e um segredo de longa duracao.
  EOT
  value       = null

  precondition {
    condition     = var.decisao_d1 != null
    error_message = local.razao_d1
  }

  precondition {
    condition     = var.fornecedor_implementado
    error_message = local.razao_costura
  }
}

output "forma_pedida" {
  description = <<-EOT
    A forma de compute que o ambiente pediu, devolvida para que o `plan` a
    mostre antes de parar. Nao depende do fornecedor nem da D1, pelo que nao
    leva precondicao: e a unica saida que se le com a D1 aberta.
  EOT
  value       = local.pedido.forma
}
