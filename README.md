# Bicho Meu — teste distribuído em navegadores

**Estado: preparado; ainda não executado. Não constitui prova de capacidade.**

O proprietário autorizou a simulação de 1.000 usuários e o aumento gradual da carga.
Este pacote permite uma execução isolada em 20 máquinas Linux do GitHub Actions,
com Chromium, JavaScript, CSS, imagens e contextos de navegador com cookies e
armazenamento separados. Cada máquina mantém sua origem durante toda a execução.
O IP de saída é medido pelo próprio Chromium e preservado nos resultados.

## Etapas globais

| Sessões pretendidas | Duração da etapa |
|---|---:|
| 100 | 60 s |
| 250 | 60 s |
| 500 | 60 s |
| 1.000 | 180 s |
| 1.500 | 120 s |
| 2.000 | 120 s |

Cada etapa inclui até 30 segundos de entrada gradual. As sessões navegam pela
home, catálogo e Camiseta Brisa, com pausas de 20–40 segundos e rolagem. Metade usa
viewport de celular e metade desktop. Não há cadastro, envio de mensagens, adição
de produtos, checkout, pedido, pagamento ou modificação da loja. O teste valida
navegação; não certifica transações simultâneas. O tráfego automatizado pode
aparecer nas ferramentas de analytics; isso não representa vendas ou clientes reais.

## Paradas e evidência

- HTTP 403/429/5xx na loja, conteúdo inesperado ou falha de navegador interrompem
  o gerador. A matriz cancela os demais trabalhos quando um gerador falha.
- P95 de carregamento acima de 15 segundos ou exaustão do gerador, persistentes
  em três verificações, interrompem o teste e são identificados separadamente.
- Não há rotação de IP, repetição para contornar bloqueios ou falsificação de
  cabeçalhos de endereço de cliente.
- O relatório soma intervalos de sessões que efetivamente abriram uma página
  válida, reconstruindo a simultaneidade observada. Não usa o alvo configurado
  como resultado medido.
- Uma aprovação exige resultados completos dos 20 geradores, pelo menos duas
  origens distintas, ausência de erros e ao menos 60 segundos acima do alvo.

## Execução preparada

1. Criar um repositório **público** dedicado somente a este código de testes.
2. Copiar estes arquivos para a raiz, incluindo `.github/workflows/capacity.yml`.
3. Em Actions, selecionar “Bicho Meu - distributed browser capacity” e executar
   manualmente “Run workflow”. Não há disparo por agenda nem por push.
4. Acompanhar os 20 trabalhos. “Cancel workflow” encerra toda a execução.
5. Obter o artefato `consolidated-result` e conferir o pico observado, as origens,
   os segundos acima de cada alvo e os erros; nunca publicar aprovação se faltarem
   geradores ou a execução tiver sido interrompida.

São usados exclusivamente runners padrão `ubuntu-24.04`. A documentação do GitHub
informa gratuidade para esses runners em repositórios públicos e concorrência de
20 trabalhos no plano Free. Não usar runners maiores pagos nem repositório privado
sem antes verificar custos e cotas. Limites, verificações da conta e filas do GitHub
podem impedir ou atrasar a execução; isso não é falha da loja.

## Validação local já possível

`python3 -m unittest -v test_aggregation.py` verifica os cálculos de simultaneidade,
a rejeição de origens iguais, resultados incompletos e intervalos não sobrepostos.
A execução real do navegador e do workflow depende do acesso ao GitHub e ainda
precisa passar pelo smoke check inicial.

## Fontes oficiais

- https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- https://docs.github.com/en/actions/reference/limits
- https://docs.github.com/en/actions/concepts/billing-and-usage
- https://playwright.dev/python/docs/browser-contexts
- https://playwright.dev/python/docs/api/class-request

Não há tokens, senhas, cookies de administrador ou dados pessoais de clientes
neste pacote. A loja alvo é fixada no código e nenhuma compra é realizada.
