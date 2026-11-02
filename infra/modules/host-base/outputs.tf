output "cloud_init" {
  description = <<-EOT
    O documento cloud-init, como texto. `sensitive` nao porque contenha um
    segredo — nao contem, e o gate 9 varre a arvore para o provar — mas porque
    leva a REFERENCIA do segredo do WireGuard e o nome do utilizador de
    administracao, e nada disso tem de aparecer num `plan` que alguem cola num
    bilhete.
  EOT
  value       = local.cloud_init
  sensitive   = true
}

output "porta_wireguard" {
  description = <<-EOT
    A porta UDP a abrir. Sai daqui para que a lista de portas do modulo de
    fornecedor venha deste modulo e nao de um numero repetido nos dois sitios —
    duas copias de uma porta divergem, e o `scan` externo do KAM-077 e que
    descobriria.
  EOT
  value       = var.porta_wireguard
}

output "quatro_coisas_do_criterio_2" {
  description = <<-EOT
    O que este modulo promete entregar, nomeado. Nao e decoracao: e o que a
    secao «Verificacao dos Criterios de Aceitacao» do bloco do KAM-075 cita, e
    o que um `plan` mostra a quem o ler. **Nenhuma destas quatro foi observada
    num host** — ver `infra/README.md` §5.
  EOT
  value = [
    "docker",
    "utilizador-nao-root:${var.utilizador}",
    "wireguard:udp/${var.porta_wireguard}",
    "nvme:${var.ponto_de_montagem_nvme}",
  ]
}
