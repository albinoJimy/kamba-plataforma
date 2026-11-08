"""A politica dos guardrails: padroes, limiares e a versao SemVer (KAM-033).

Os Detalhes Tecnicos do bloco pedem «padroes em ficheiros de politica
versionados em SemVer». E este ficheiro, e a versao e o `VERSAO_DA_POLITICA`.

## A versao e uma promessa, e ha ensaio que a cobra

`impressao()` e o SHA-256 de **tudo** o que decide um veredicto: os padroes, a
ordem em que estao e os limiares. A bateria fixa a impressao de cada versao
(`test_guardas.py::TestPolitica`), pelo que mudar um padrao sem subir a versao
avermelha a suite — e um padrao e um artefacto comportamental (DoD,
«Eval-gate»): dois grafos com a mesma versao e regras diferentes eram duas
respostas diferentes com o mesmo nome no `golden`.

A regra de subida e a do `VERSAO_DO_GRAFO`: *patch* para uma correccao que so
estreita um falso positivo, *minor* para um padrao novo, *major* para um
veredicto novo ou retirado.

## Os padroes correm sobre o texto **dobrado**, e nunca sobre o texto cru

`regras.normalizar` tira os caracteres de controlo e de largura zero, aplica
`NFKC` (que reduz as formas de largura total e as de compatibilidade) e depois
o `dobrar` do KAM-112: minusculas, sem acentos, digitos Unicode em ASCII. Por
isso **todos** os padroes abaixo estao escritos sem acentos e em minusculas — e
a primeira versao da guarda (KAM-031) corria-os sobre o texto cru com
`IGNORECASE`, pelo que «aceitam **crédito**?» nao casava `credito` e passava.

## Os limiares sao *proposta*

O `TENTATIVAS_DE_INJECCAO`, a janela e o *cool-down* vem do `docs/tecnica/08`
§4.3 (L5: «3 tentativas/h por contacto -> handoff e *cool-down*»), que nao da
duracao ao *cool-down*. O `OCORRENCIAS_DE_ABUSO` e o «N *proposta*» do criterio
5. Calibram-se no *golden* (KAM-040) e no Piloto (KAM-109).
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

#: A versao desta politica. Ver a nota do modulo para a regra de subida.
VERSAO_DA_POLITICA: Final = "1.0.0"

# ------------------------------------------------------------------- limiares

#: Tentativas de injeccao, na janela, que levam a *handoff* e *cool-down*
#: (`docs/tecnica/08` §4.3, L5). *Proposta*.
TENTATIVAS_DE_INJECCAO: Final = 3
#: A janela das tentativas, em segundos: uma hora, que e a unidade do §4.3.
JANELA_DE_INJECCAO_S: Final = 3_600
#: O *cool-down* depois do *handoff*, em segundos. *Proposta*: o §4.3 nomeia-o
#: sem lhe dar duracao, e uma hora e a mesma ordem da janela.
COOLDOWN_S: Final = 3_600
#: Ocorrencias de abuso, na conversa, que a passam a `pausada` (criterio 5, «N
#: *proposta*»).
OCORRENCIAS_DE_ABUSO: Final = 3
#: O comprimento a partir do qual o texto e cortado **antes** de ir ao
#: classificador (`docs/tecnica/08` §4.3, L1: «limite de comprimento»). As
#: regras correm sobre o texto inteiro; o corte e so do que sai para o modelo.
COMPRIMENTO_MAXIMO: Final = 1_000

# --------------------------------------------------------- padroes de entrada

#: Instrucoes ao sistema, pedidos de revelar o *prompt*, troca de papel
#: (§8.4, primeira linha; `docs/tecnica/08` §4.3, L1).
INJECCAO: Final = (
    r"\bignor(?:a|e|ar|em|ando)\b.{0,40}\b(?:instruc|regras|ordens|orientac|prompt|restric|limites)",
    r"\besquec(?:e|a|er|am)\b.{0,25}\b(?:tudo|instruc|regras|o que te|as ordens)",
    r"\b(?:revela|revele|mostra|mostre|diz|diga|repete|repita|escreve|escreva|imprime|copia|cola|partilha)\b"
    r".{0,30}\b(?:o (?:teu|seu) prompt|as (?:tuas|suas) instruc|instruc\w* (?:do sistema|iniciais|internas|secretas|originais)"
    r"|mensagem (?:do|de) sistema|regras internas|configurac\w* interna|o prompt)",
    r"\bsystem prompt\b",
    r"\bprompt (?:do|de) sistema\b",
    r"\bage como\b",
    r"\baja como\b",
    r"\b(?:finge|finja|fingir)\b.{0,10}\b(?:que|ser)\b",
    r"\bfaz de conta\b",
    r"\ba partir de agora (?:es|e|sera|vais ser|voce e|tu es)\b",
    r"\b(?:tu|voce) agora (?:es|e)\b",
    r"\bmodo (?:dev|desenvolvedor|developer|admin|administrador|deus|jailbreak|sem filtros)\b",
    r"\bjailbreak\b",
    r"\b(?:assistente|modo|bot|ia|responde|responder|fala|falar)\b.{0,15}\bsem (?:regras|restricoes|filtros|limites|censura)\b",
    r"\bnovas instrucoes\b",
    r"\b(?:desactiva|desativa|desliga|remove)\w*\b.{0,15}\b(?:regras|filtros|guardas|seguranca|restricoes)\b",
    # Delimitadores falsos: quem os escreve quer fechar o bloco de dados e abrir
    # um de sistema. Ver o `prompt.py`, que os neutraliza do outro lado.
    r"<\s*/?\s*(?:system|sistema|instrucoes|dados[_a-z]*|assistant|user)\s*>",
    r"\[\s*/?\s*(?:system|inst|sistema)\s*\]",
    r"#{2,}\s*(?:system|sistema|instruc)",
)

#: Pedidos que atravessam a fronteira do *tenant* ou do contacto: o X-09 do
#: `docs/tecnica/08` §3.7. **E a metade do X-09 que vive na guarda**: a outra
#: esta na tool, que so ve encomendas do proprio contacto, e a terceira na RLS.
#:
#: Os dois primeiros padroes exigem um **verbo de pedido**, um **substantivo de
#: dados de clientes** e um **qualificador de terceiro**: «os pedidos da loja
#: demoram?» e uma pergunta sobre esta loja, e «mostra os pedidos da loja Kero» e
#: o X-09. O `tem`/`tens` **nao** e verbo de pedido, e mediu-se porque: «o pedido
#: da loja tem atraso?» casava o segundo padrao e saia como `injection`.
_VERBO: Final = (
    r"(?:mostra|mostre|lista|liste|listar|da-me|de-me|envia|envie|manda|mande|exporta|exporte|"
    r"quero ver|queria ver|posso ver|deixa-me ver|consulta|consulte|abre|abra|acede|aceda|"
    r"passa-me|passe-me|diz-me|diga-me|quais sao|quem sao|preciso d[eo]s?)"
)
#: Dados **de clientes**. Sem `dados`, `stock` nem `numeros` nesta lista: «preciso
#: dos dados da loja para a factura» e o cliente a pedir o NIF da loja, e
#: «mostra o stock da loja» e uma pergunta de catalogo.
_DADOS_DE_CLIENTES: Final = (
    r"pedidos?|encomendas?|clientes?|vendas?|contactos?|telefones?|moradas?|enderecos?|"
    r"facturas?|faturas?|compras?|historicos?|conversas?|mensagens?|emails?|e-mails?|"
    r"faturacao|facturacao|lucros?"
)
_DADOS: Final = rf"(?:{_DADOS_DE_CLIENTES})"
#: Para o terceiro padrao, que **ja** exige «outros clientes» ao lado, a lista
#: alarga-se ao que so faz sentido sobre terceiros.
_DADOS_DE_TERCEIROS: Final = rf"(?:{_DADOS_DE_CLIENTES}|dados|nomes?|numeros?)"
_TERCEIRO: Final = (
    r"(?:(?:d[aoe]|na|no)\s+(?:outr[ao]s?\s+)?(?:loja|lojas|empresa|empresas|tenant|tenants|vendedor|vendedores|concorrente|concorrencia)"
    r"|outr[ao]s? (?:clientes?|contactos?|lojas?|utilizadores?|usuarios?|compradores?|pessoas?|vendedores?|empresas?)"
    r"|tod[oa]s? (?:os |as )?(?:clientes|contactos|lojas|utilizadores|vendedores|empresas)"
    r"|(?:loja|lojas) (?:do lado|vizinha|vizinhas|concorrente|concorrentes|ao lado))"
)
FRONTEIRA: Final = (
    rf"\b{_VERBO}\b.{{0,30}}\b{_DADOS}\b.{{0,30}}\b{_TERCEIRO}\b",
    rf"\b{_DADOS}\b.{{0,30}}\b{_TERCEIRO}\b.{{0,30}}\b{_VERBO}\b",
    rf"\b{_DADOS_DE_TERCEIROS}\b.{{0,20}}\b(?:outr[ao]s? (?:clientes?|contactos?|lojas?|utilizadores?|compradores?|pessoas?))\b",
    rf"\b{_VERBO}\b.{{0,20}}\btod[oa]s? (?:os |as )?(?:pedidos|encomendas|vendas|clientes|contactos)\b",
    r"\b(?:outro|outra|qualquer) tenant\b",
    r"\btenant[_ ]?id\b",
    # Um UUID no texto do cliente e um identificador nosso, nunca dele.
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    r"\bselect\s+\*|\bunion\s+select\b|\bdrop\s+table\b|;\s*--",
)

#: O que **absolve** um padrao de fronteira: o cliente a falar dos pedidos dele.
#: A revisao adversarial do KAM-031 mediu o custo de nao ter isto (achado 6).
PRIMEIRA_PESSOA: Final = (
    r"\b(?:meu|meus|minha|minhas|que fiz|que encomendei|que comprei|da minha conta|em meu nome)\b"
)

#: Assunto sensivel (§8.4, quarta linha; `docs/tecnica/08` §7.5; criterio 7).
#: Vai a *handoff* e nao a `safe_reply`, porque o §7.3 linha 10 o manda.
#:
#: **O alcool entra agora**, e era a divida que o KAM-031 deixou com este ticket
#: como credor: o criterio 7 nomeia-o e a Meta proibe-o no comercio (CONFIRMADO,
#: E1 §4). O custo que aquele ticket temia — a *handoff* de toda a pergunta
#: sobre cerveja numa loja que a venda — e o que as **categorias da loja**
#: resolvem, e essas sao do KAM-088 (o *Handoff* deste bloco: «politica de
#: categorias (KAM-088) e ticket proprio»). Ate la, uma pessoa decide.
SENSIVEL: Final = (
    # Saude e medicamentos.
    r"\bmedicament\w*", r"\bremedi\w*", r"\breceita medica\b", r"\bdoenc\w*", r"\bsintoma\w*",
    r"\bcomprimido\w*", r"\bantibiotic\w*", r"\bxarope\w*", r"\bpaludismo\b", r"\bmalaria\b",
    r"\bdiabet\w*", r"\bhiv\b", r"\bseropositiv\w*", r"\btensao alta\b", r"\bhipertens\w*",
    r"\bconsulta medica\b",
    # Armas.
    r"\barma\b", r"\barmas\b", r"\barma de fogo\b", r"\bespingarda\w*", r"\bpistola\w*", r"\bmunic\w*",
    # Alcool (ver a nota acima).
    r"\balcool\w*", r"\bcerveja\w*", r"(?<!cor de )(?<!cor )\bvinho\w*", r"\bwhisky\w*", r"\buisque\w*", r"\bwhiskey\b",
    r"\bvodka\b", r"\bgin\b", r"\baguardente\w*", r"\bcaporroto\b", r"\bkissangua\b", r"\bbebidas? alcoolic\w*",
    # Apostas.
    r"\baposta\w*", r"\bapostar\b", r"\bcasino\w*", r"\bcasseno\b", r"\blotaria\w*", r"\bbetting\b",
    # Credito como produto. **Nao** o meio de pagamento: «aceitam cartao de
    # credito?» e das perguntas mais frequentes de uma loja (achado 8 do
    # KAM-031).
    r"\bemprestimo\w*", r"\bmicrocredito\w*", r"(?<!cartao de )(?<!cartao )\bcredito\w*",
    r"\bfinanciamento\w*", r"\bpagar (?:em|as) prestac\w*", r"\ba prestacoes\b",
    # Dados sensiveis do Art. 5.o c) que o `docs/tecnica/08` §7.5 acrescenta.
    r"\breligiao\b", r"\borientacao sexual\b", r"\bvida sexual\b", r"\bpartido politico\b",
    r"\bfiliacao partidaria\b", r"\bem quem votar\b",
)

#: Conteudo ofensivo e ameacas (§8.4, quinta linha).
ABUSO: Final = (
    r"\bestupid\w*", r"\bidiota\w*", r"\bimbecil\w*", 
    # O `burro` e o `palhaco` so com quem os diz a alguem: «o burro de peluche»
    # e um brinquedo.
    r"\b(?:seu|sua|es|e|sao|um|uns|que)\s+(?:um |uns )?(?:burr[oa]s?|palhac[oa]s?)\b",
    r"\botari[oa]s?\b", r"\bcabra[oa]\w*", r"\bmerda\w*", r"\bputa\w*", r"\bcaralh\w*",
    r"\bfoda-?se\b", r"\bfoder\b", r"\bvai-te foder\b", r"\bcorno\w*", r"\bnojent\w*",
    r"\bdesgracad\w*", r"\bmatumbo\w*", r"\bbandid[oa]s?\b", r"\bladr[oa]\w*\b", r"\bladroes\b",
    r"\bcala(?:-te| a boca| a matraca)\b", r"\bvou-te (?:matar|partir|bater)\b",
    r"\bvou (?:matar|partir|queimar|rebentar)\b.{0,20}\b(?:te|vos|loja|voces|a loja|tudo)\b",
)

#: Fora do dominio: o «assistente universal» que a Meta proibe como
#: funcionalidade principal (CONFIRMADO, E1 §4). Recusa-se com redireccionamento
#: ao ambito da loja, e conta-se na metrica agregada que e a prova de ambito.
FORA_DE_DOMINIO: Final = (
    r"\b(?:escreve|escreva|faz|faca|cria|crie|redige|redija|compoe|componha|gera|gere)\b.{0,25}"
    r"\b(?:poema|poesia|cancao|musica|letra de|redaccao|redacao|composicao|ensaio|historia|conto|piada|"
    r"codigo em \w+|programa de computador|script|carta de amor|curriculo|discurso|trabalho de casa|tpc|resumo do livro)\b",
    r"\btraduz\w*\b",
    r"\btraducao\b",
    r"\b(?:resolve|resolva|calcula|calcule)\b.{0,20}\b(?:equacao|exercicio|problema|integral|derivada)\b",
    r"\bqual (?:e )?a capital d[eao]s?\b",
    r"\bquem (?:foi|e|era) o (?:presidente|primeiro|inventor|autor|descobridor)\b",
    r"\bquem ganhou (?:o|a|as|os)\b",
    r"\b(?:previsao do tempo|vai chover|meteorologia)\b",
    r"\b(?:conta|conte|diz|diga)(?:-me)? (?:uma |um )?(?:piada|anedota|historia)\b",
    r"\b(?:receita de|como (?:se )?(?:faz|cozinha|prepara)) (?:um |uma |o |a )?(?:bolo|funge|muamba|calulu|comida|prato|pao)\b",
    r"\bajuda(?:-me)? (?:com|no|na) (?:o |a )?(?:meu |minha )?(?:trabalho de casa|tpc|exame|teste da escola|tese|monografia)\b",
    r"\bexplica(?:-me)?\b.{0,30}\b(?:historia de|guerra|ciencia|fisica|quimica|biologia|matematica|filosofia|bitcoin|blockchain)\b",
    r"\b(?:sentido da vida|o que achas d[aoe]s? (?:governo|eleicoes|futebol|politica))\b",
    r"\b(?:es|e) capaz de (?:responder a tudo|fazer qualquer coisa)\b",
    r"\bnoticias d[eo] (?:hoje|dia|mundo|angola)\b",
)

#: O lexico do dominio comercial. **E o que deixa as regras decidir `ok`** sem
#: ir ao classificador: uma mensagem que fala de preco, pedido ou entrega e da
#: loja, e o §8.4 manda o classificador so quando as regras nao decidem.
DOMINIO: Final = (
    r"\b(?:preco|precos|custa|custam|quanto|valor|comprar|compro|levar|levo|encomend\w*|pedido\w*|"
    r"entrega\w*|entregar|stock|disponivel|disponiveis|tem|teem|tens|vendem|vende|vendes|"
    r"pagamento|paguei|pagar|pago|transferenc\w*|multicaixa|referencia|loja|horario|aberto|abrem|"
    r"fecha\w*|morada|endereco|onde fica|onde estao|troca\w*|devolu\w*|tamanho|cor|modelo|marcar|"
    r"marcacao|agendar|agenda|reservar|reserva|vaga|vagas|servico|servicos|cancelar|cancela|desconto|"
    r"promocao|catalogo|produto\w*|artigo\w*|camisa\w*|vestido\w*|sapato\w*|roupa\w*|unidades|"
    r"falar com|humano|atendente|colega|pessoa|obrigad\w*|bom dia|boa tarde|boa noite|ola|confirm\w*|"
    r"carrinho|quero|queria|procuro|ha|existe|chegou|saiu|estado|aceitam|aceita|rua|bairro|moro|"
    r"contribuinte|nif|factura|fatura|recibo)\b",
)

# ----------------------------------------------------------- padroes de saida

#: Promessas proibidas (§8.4: «descontos, prazos de entrega, "pago/confirmado"
#: sem evento, comparacoes»; criterio 6). Agrupadas por familia, porque o
#: `test_guardas.py` mede cada uma com casos proprios.
PROMESSA_DESCONTO: Final = (
    r"\b(?:desconto|descontos|preco especial|em promocao|promocao|promocoes|saldos?|oferta especial|"
    r"gratis|gratuit\w*|de borla|sem custo|leve \w+ pague|oferecemos)\b",
    r"\b(?:preco|custa|custo)\b.{0,12}\b(?:zero|nada)\b",
)
PROMESSA_PRAZO: Final = (
    r"\b(?:chega|chegam|chegara|chegarao|entregamos|entregaremos|entrega-se|recebe|recebera|fica pronto|esta pronto)\b"
    r".{0,25}\b(?:amanha|hoje|depois de amanha|esta semana|na proxima semana|ate (?:sexta|segunda|terca|quarta|quinta|sabado|domingo|ao fim do dia)|em (?:poucas|duas|tres|\d+) (?:horas|dias))\b",
    r"\bentrega (?:garantida|imediata|no mesmo dia|expresso garantid\w*|amanha|hoje)\b",
    r"\bprazo de entrega (?:e|de|sao)\b",
)
PROMESSA_PAGO: Final = (
    r"\b(?:ja|esta|foi|ficou)\s+(?:esta\s+)?(?:pago|paga|liquidad[oa]|confirmad[oa])\b",
    r"\b(?:pagamento|transferencia)\b.{0,20}\b(?:confirmad[oa]|recebid[oa]|aprovad[oa]|validad[oa])\b",
    r"\b(?:pedido|encomenda)\b.{0,15}\b(?:esta |foi |ficou )(?:pag[oa]|confirmad[oa])\b",
)
PROMESSA_COMPARACAO: Final = (
    r"\b(?:o|a|os|as) mais barat[oa]s?\b",
    r"\bmais barat[oa]s? (?:da|do|que|de|em)\b",
    r"\b(?:melhor|menor) preco\b",
    r"\bnao ha (?:mais barato|melhor)\b",
    r"\bmais (?:em conta|economic[oa]s?) (?:da|do|que)\b",
    r"\bconcorrencia\b",
    r"\btemos sempre\b",
    r"\bnunca (?:falta|esgota)\b",
    r"\bstock garantido\b",
)

#: Identidade e transparencia: eco do *system prompt* e pretender ser humano
#: (§8.4; `docs/tecnica/08` §4.3, L4: «detecao de eco do system prompt»).
IDENTIDADE: Final = (
    r"\b(?:as minhas|minhas|as nossas) instrucoes\b",
    r"\bsystem prompt\b",
    r"\bprompt (?:do|de) sistema\b",
    r"\bfui (?:instruid[oa]|programad[oa]|configurad[oa]|treinad[oa]) (?:para|a)\b",
    r"\b(?:sou|es|como) (?:um )?modelo de linguagem\b",
    r"\bregras internas\b",
    r"\bkamba[-_ ]?(?:router|chat|vision|embed)\b",
    r"<\s*/?\s*(?:system|sistema|dados[_a-z]*)\b",
    r"\bsou (?:um |uma )?(?:humano|humana|pessoa real|pessoa de verdade|funcionari[oa] humano)\b",
    r"\bnao sou (?:um |uma )?(?:bot|robo|assistente automatico|programa)\b",
)

#: Fuga de dados (§8.4: «nada de telefone em claro»; `docs/tecnica/08` §4.3 L4:
#: «telefones e NIF de terceiros, URLs fora da allowlist, sem imagens/markdown
#: remotos»). O telefone e o e-mail **nao** estao aqui: usam-se os padroes do
#: detector do KAM-112, que tem corpus e recall medidos, e duas expressoes para
#: o mesmo identificador divergiam no dia em que alguem corrigisse uma.
FUGA: Final = (
    # NIF/BI por contexto. **Nao se inventa o formato** (o `privacidade/detector`
    # deixou o `PADRAO_DE_NIF` a `None` pela mesma razao): o que se recusa e um
    # identificador longo **depois** da palavra que o nomeia.
    r"\b(?:nif|contribuinte|bilhete de identidade|bi n\w*|n\.?o? de bi)\b\W{0,6}(?:n\.?o?\s*)?[a-z0-9]{6,}",
    # Imagem *markdown* remota: o pedido HTTP do cliente e a exfiltracao (§4.4).
    r"!\[[^\]]*\]\(",
)
#: Nove ou mais digitos seguidos **fora** de um numero de negocio (o `reclamar`
#: do KAM-112): a forma de um telefone sem separadores, de um NIF e de um numero
#: de conta. Um total de «912500000 Kz» e reclamado como dinheiro e passa.
FUGA_DIGITOS: Final = r"(?<![0-9])[0-9]{9,}(?![0-9])"
#: Pedir dados de cartao ou de conta. O `saida.py` exige que **nao** venha
#: negado («nao envie»), que e o que o `MSG_CARTAO` diz.
FUGA_PEDIDO_DE_DADOS: Final = (
    r"\b(?:envie|envia|mande|manda|indique|indica|diga|diz|partilhe|digite|escreva|introduza|confirme)\b"
    r".{0,25}\b(?:numero do cartao|dados do cartao|o (?:seu |teu )?cartao|pin|cvv|codigo de seguranca|iban|"
    r"numero de conta|palavra-passe|senha|password)\b"
)

#: Um URL ou um dominio. O hospedeiro compara-se com a *allowlist* do grafo.
URL: Final = (
    r"\b(?:https?://|www\.)[^\s<>()\"']+",
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|ao|net|org|pt|io|me|ly|link|xyz|info|biz|co|app|site|online|shop|store)\b(?:/[^\s<>()\"']*)?",
)


def impressao() -> str:
    """O SHA-256 de tudo o que decide um veredicto, pela ordem em que decide.

    Inclui o *system prompt* do classificador: e tao comportamental como um
    padrao, e muda-lo muda o que o `kamba-router` devolve.
    """
    from .prompt import FRASE_DO_SISTEMA, SISTEMA_DO_CLASSIFICADOR

    conteudo = {
        "prompt": [SISTEMA_DO_CLASSIFICADOR, FRASE_DO_SISTEMA],
        "limiares": [
            TENTATIVAS_DE_INJECCAO,
            JANELA_DE_INJECCAO_S,
            COOLDOWN_S,
            OCORRENCIAS_DE_ABUSO,
            COMPRIMENTO_MAXIMO,
        ],
        "entrada": [INJECCAO, FRONTEIRA, PRIMEIRA_PESSOA, SENSIVEL, ABUSO, FORA_DE_DOMINIO, DOMINIO],
        "saida": [
            PROMESSA_DESCONTO,
            PROMESSA_PRAZO,
            PROMESSA_PAGO,
            PROMESSA_COMPARACAO,
            IDENTIDADE,
            FUGA,
            FUGA_DIGITOS,
            FUGA_PEDIDO_DE_DADOS,
            URL,
        ],
    }
    return hashlib.sha256(json.dumps(conteudo, ensure_ascii=True).encode()).hexdigest()
