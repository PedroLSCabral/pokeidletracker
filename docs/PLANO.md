# PokeIdle Tracker: plano e notas

> Projeto pessoal e não oficial, sem relação com a equipe do pokeidle.io. Este arquivo é o diário do projeto: o plano original, o que foi descoberto sobre o jogo e as decisões tomadas, na ordem em que aconteceram.

> Os caminhos de arquivo citados aqui são os da época de cada entrada. Em 10/11 as pastas foram reorganizadas (`src/coleta/`, `src/analise/`, `src/web/`, `legado/`, `docs/`); a estrutura atual e o papel de cada módulo estão em [ARQUITETURA.md](ARQUITETURA.md).

Painel de análise de preços do mercado RMT do Poké Idle.io (preços em gemas), montado a partir do histórico de compras que o próprio jogo exporta.

## Objetivo

1. Clicar num item (fragmento de bicicleta, casa, pedra shiny, pedra de mega etc.) e ver na hora:
   - preço médio, mediana, mínimo e máximo
   - volume (quantas unidades foram negociadas)
   - janelas de **24h / 7d / 30d / tudo**
   - gráfico de preço ao longo do tempo (diário, com faixa de mínimo e máximo)
2. Não precisar mais exportar e importar a planilha na mão.
3. Mais adiante, usar a mesma base para analisar o mercado de Pokémon.

## Fases

### Fase 1: importar a planilha e mostrar o painel (MVP)
- **Importador**: lê o arquivo exportado (CSV/XLSX), normaliza os dados e grava num banco SQLite local.
  - Remove duplicatas: cada exportação nova repete vendas antigas. Como não existe ID, os minutos completos do export novo substituem os do banco, e o minuto mais antigo (que pode vir cortado) só é completado.
  - Pasta `data/inbox/`: qualquer arquivo colocado ali é importado e depois movido para `data/processed/`.
- **Painel**: Python + Streamlit (o caminho mais rápido para ter gráficos interativos e filtros sem escrever frontend).
  - Lista de itens com o preço atual e a variação em 7d (ex.: bicicleta 130 → 170, +30%)
  - Página do item: gráfico de preço com seletor de janela e as estatísticas acima
  - Calculadora de taxa: preço de venda → valor líquido recebido, e o preço mínimo para revender sem prejuízo

### Fase 2: automatizar a exportação (prioridade alta)
**Por que ficou urgente:** o export só traz as **5.000 vendas mais recentes**, e no ritmo atual isso cobre só **~2h20** do mercado (16:29 → 18:47 na primeira planilha). Como dá para baixar **1 vez por hora por IP**, um export por hora deixa ~1h de sobreposição. Ficar mais de ~2h sem exportar significa vendas **perdidas para sempre**. O importador avisa quando isso acontece.
- Coleta de hora em hora, 24h por dia. O PC precisa estar ligado; se os buracos à noite incomodarem, mais tarde dá para rodar numa máquina sempre ligada (VPS barata, Raspberry Pi).
- Num evento com volume mais que ~2× o atual, até o export de hora em hora começa a perder vendas. O registro de importações vai mostrar isso.

Depende de como o botão de exportar funciona por baixo dos panos; isso precisa ser investigado:
- **Opção A (preferida)**: o botão chama uma API (JSON/CSV) do site. Nesse caso um script chama o mesmo endereço usando a sua sessão logada e salva o resultado direto no banco.
- **Opção B**: se não houver API utilizável, o Playwright abre o site com o seu login salvo, clica em exportar e joga o arquivo em `data/inbox/`.
- Agendamento: Agendador de Tarefas do Windows, 1 a 4 vezes por dia. Uma frequência baixa já basta para preços que mudam de um dia para o outro, e não sobrecarrega o servidor.
- ⚠️ Antes disso, ler os Termos de Uso: alguns jogos com economia real proíbem automação e banem contas por isso. Se proibirem, a gente fica com a Fase 1 e uma exportação manual rápida.

### Fase 3: alertas e sinais (feito em 08/11)
- `src/sinais.py` calcula, por item e moeda:
  - **oportunidade de revenda:** comprar no menor anúncio e revender pela referência (a menor entre as medianas de 24h e 7d; exige 10+ vendas em 7d), já com a taxa de 15% arredondada para cima;
  - **barato/caro:** mediana de 24h contra a de 7 dias (só aparece depois de 36h de coleta);
  - **liquidez:** vendas por dia (alta ≥ 20, média ≥ 5, baixa < 5).
- **Regras de alerta** ficam no banco (`alertas_regras`) e são editadas na aba **Sinais** do painel. Tipos: margem de revenda ≥ X%, menor anúncio ≤ X, mediana 24h ≥ X, variação 7d ≥ X%. Valem para um item ou para qualquer item. Regra inicial: qualquer item, margem ≥ 10%, sem liquidez baixa.
- **Anúncio abaixo de ¼ da referência fica fora da revenda e dos alertas (09/11).** É a mesma regra das vendas fora da curva. Várias pedras têm dois mercados em gemas, com lotes vendidos a 2 gemas por unidade e unidades avulsas a ~20–200 gemas. Comparar um com o outro disparava alertas de +1.000% a +7.700%. A aba Sinais lista esses itens embaixo da tabela.
- **O robô confere as regras depois de cada coleta** (a cada minuto, com a vitrine; eram 15 min até 09/11). O mesmo alerta não se repete por 6h, a menos que fique 5% melhor. Mais de 5 alertas de uma vez viram uma mensagem só. Tudo vai para `alertas_log`, que aparece no painel.
- **Canais** (`src/notificar.py`), configurados em `config.local.json`, no bloco `"alertas"`:
  - `"windows": true`: notificação nativa (padrão no Windows, sem instalar nada).
  - `"discord_webhook": "https://discord.com/api/webhooks/..."`: num servidor seu, Configurações do canal → Integrações → Webhooks → Novo webhook → Copiar URL.
  - `"telegram_token"` + `"telegram_chat_id"`: crie um bot com o @BotFather e pegue o seu chat id.
  - O botão "enviar notificação de teste" da aba Sinais testa todos os canais configurados.
  - **Aviso sonoro no painel:** com a página aberta, ela confere novos alertas a cada 30 s, toca um som 8-bit gerado na hora (arpejo de moeda para oportunidade, dois toques para os demais), mostra o aviso no canto da tela (clicar abre o item) e põe "(n)" no título da aba se ela estiver em segundo plano. O botão "♪" no topo liga/desliga (a escolha fica salva no navegador). O navegador só libera áudio depois do primeiro clique na página; até lá o botão pisca.
- **Primeira leitura (08/11, 13h):** nenhuma revenda com lucro. Depois da taxa, todas as margens são negativas (a melhor foi o Bicycle Fragment, com −4%). O mercado dos itens líquidos está eficiente; os alertas servem para pegar desvios raros.
- **Limites:** a vitrine traz só o menor preço, não quantas unidades há nele; um anúncio barato some em segundos (trava de 2 min + sorteio entre compradores); revender pela mediana pode demorar.

Ideias originais desta fase:
- Alerta (notificação ou Telegram) quando um item passar de X gemas ou subir Y% em 7 dias
- Comparar o preço atual com a média de 30 dias (item "barato" ou "caro" agora)
- Volume baixo = sinal de pouca liquidez (difícil vender rápido)

### Fase 4: mercado de Pokémon (feito em 08/11)
- **Loja inteira lida a cada 3h** (`src/lojapk.py` + `varrer_loja_pokemon` no robô): `market.listar` página por página (24 por página, ~6.300 anúncios, ~260 páginas), com 1 s entre páginas. Cada anúncio guarda a ficha completa (espécie, nível, shiny, nota, poder, IVs, stats, qualidade, potência, tipos, refino, TMs), preço, moeda, vendedor e validade em `pk_anuncios`. Anúncio que some entre varreduras completas vira inativo (vendido, cancelado ou vencido). Uma varredura que falha só tenta de novo 30 min depois.
- O robô agora usa uma **sessão com leitor em segundo plano** (`Sessao` em robo.py): pede, espera a resposta certa e mantém ping a cada 25 s, o que aguenta sessões longas.
- **Preço justo** (`src/analise_pokemon.py`), com vendas dos últimos 14 dias, em duas camadas:
  1. **Vendas parecidas:** mesma espécie, mesmo shiny, mesma moeda, mesma faixa de nível e de nota, sem as absurdas (fora de 4× a mediana). Com 5+, vale a mediana (confiança alta com 8+, média com 5–7). P4/P5 recebem o multiplicador da potência.
  2. **Modelo de multiplicadores:** log(preço) = base da espécie + nível + nota + potência, uma regressão com efeito fixo por espécie resolvida por médias alternadas. Vendas mais de ~5× fora do previsto saem e o ajuste é refeito. Confiança média só se a espécie já vendeu naquela faixa de nível; extrapolar dá confiança baixa.
  - Primeira versão (k-vizinhos e depois medianas) descartada nos testes: dava "preço justo 629" para um Pokémon de 10 gemas e não aprendia o efeito do nível.
  - **Multiplicadores aprendidos (gemas, 08/11):** nível 201–500 ≈ 2,4×, 501–1.000 ≈ 4,1×, 1.000+ ≈ 12,9×; nota 3,9–4,1 ≈ 1,9×, 4,1–4,3 ≈ 3,8×, 4,3+ ≈ 8,1×; P3 ≈ 1,4×, P4 ≈ 1,6× (P5 ainda com poucas vendas).
- **Teto de páginas do jogo:** o servidor não passa da página 200 (≈ 4.824 anúncios por consulta). Por isso a varredura vai por moeda e, quando passa disso, lê também do mais caro para o mais barato. A primeira varredura completa (08/11 13:41) leu **6.291 de 6.303 anúncios em 268 páginas, em 5 min 18 s**.
- **Busca por orçamento** (aba Pokémon → Encontrar Pokémon): "quero pagar até X", com filtros (espécie, tipo, potência, nível, nota, shiny) e objetivo:
  - equilibrado (60% força + 40% desconto)
  - mais forte (poder)
  - maior desconto contra o preço justo
  - mais poder por gema
  - maior nota

  Mostra também a revenda líquida (taxa progressiva + diária em coins).
- **Padrões** (aba Pokémon → Padrões do mercado): volume, mediana, % shiny, oferta na loja, quanto cada atributo multiplica o preço *relativo à mediana da espécie*, espécies mais negociadas com dias de estoque, vendas por hora, maiores compradores e vendedores, e uma tabela da taxa progressiva.
- **Primeiras leituras (08/11, ~1 dia de dados, gemas):**
  - a **nota** manda no preço: 3,9–4,1 ≈ 2,7× a mediana da espécie, 4,1+ ≈ 7–10×;
  - **nível 1.000+** ≈ 9×; **P5** ≈ 1,45× (só 9 vendas);
  - **shiny** ≈ 73× o comum da mesma espécie (6 espécies comparáveis);
  - **piso de 10 gemas:** meia dúzia de compradores compram em volume a ~10 gemas. Esse é o preço mínimo prático de um Pokémon comum. Hipótese: viram matéria-prima (Oferenda: 5 Pokémon = 1 pedra garantida).

Ideias originais desta fase:
É bem mais difícil que itens, porque cada Pokémon é único (espécie, shiny, nível, IVs/atributos, raridade). Não existe "preço do Pikachu", existe preço de *Pikachu com tais características*.
- Registrar os atributos de cada venda
- Agrupar por espécie + shiny + faixa de atributos para ter preços comparáveis
- Só faz sentido quando já houver bastante histórico; por isso fica por último

### Vender o que dropou (feito em 09/11)
Botão **vender** em cada item da lista do mercado e no título do detalhe. Abre uma janela com a quantidade e três respostas (`src/venda.py`, rota `/api/venda`):
- **Em qual moeda.**
  - O câmbio vem da razão das medianas dos itens vendidos nas duas moedas nas últimas 48 h, pesada pelo volume. Em 09/11 dava ~5,1 mi coins por gema.
  - Para virar gema, o coin ainda paga outra taxa de 15% (comprar algo em coins e vender em gemas). Por isso coins só ganha se render 5% a mais depois dessa troca.
  - Se o item quase não vende em gemas e vende bem em coins, a indicação é coins, com aviso.
- **Por quanto anunciar.** Todos os preços já descontam a taxa e saem com o total em gemas e em dólar:
  - *rápido:* 1 abaixo do menor anúncio, com a espera estimada pelo ritmo de compras;
  - *normal:* a mediana das últimas 12 h;
  - *paciente:* o percentil 75 das vendas de 48 h.

  Cada preço mostra quantas vendas de 48 h saíram a esse valor ou mais. Num mercado fino, o preço rápido some quando ficar em 1º da fila seria dar o item.
- **Quando vender.**
  - A tendência é uma reta robusta (Theil-Sen) no log das medianas por hora. A oscilação normal sai dos resíduos dessa reta.
  - A média de 7 dias do jogo, acompanhada snapshot a snapshot, mostra a semana mesmo com poucos dias de coleta.
  - Saídas possíveis:
    - pico: vender agora;
    - queda constante: vender logo;
    - queda passageira: esperar, anunciando pelo preço normal;
    - alta constante: pode segurar até 3 dias, só se o ganho passar da oscilação, e nunca "para sempre";
    - sinais mistos: os últimos dias contra a semana;
    - estável.
  - Em "esperar" e "segurar" há um botão que cria o alerta "mediana 24h ≥ alvo".
- **Confiança:** baixa com menos de 3 dias de coleta, média até 7 dias. O horário com mais compras só aparece com 3+ dias.
- **Fragmentos:** a janela também compara vender com juntar 10 e montar (valor esperado, com e sem as raridades altas).

### PvP (feito em 09/11)
Aba Pokémon → **PvP**, mais o objetivo "melhor para PvP" na busca de Pokémon.
- **De onde vêm os dados.** O botão "Tracker" do PvP abre `pokeidle.io/tracker`, um site público com JSON em `/tracker/api/*`:
  - `jogador?nick=` traz o perfil, o rank, os counters do jogador (para quem ele mais perde), as vítimas e as últimas 20 partidas com os dois times;
  - `meta?faixa=` traz as espécies com uso, vitórias e dano;
  - `pokemon?id=` traz quem ganha e quem perde de cada espécie;
  - `ladder` traz o ranking.

  Não precisa de login, então não toca nas contas nem derruba o Idle Deck.
- **Pedidos com calma** (`src/pvp.py`):
  - 1,5 s entre um pedido e outro;
  - cache no banco (`pvp_cache`): 5 min para o seu perfil, 6 h para o meta e os times do topo, 12 h para as páginas de espécie;
  - se o site recusar ou cair, usa a cópia guardada;
  - o robô pré-carrega o meta e os 10 primeiros do ranking a cada 6 h, numa thread à parte para não atrasar a vitrine.
- **A análise:**
  - **Seu time:** as espécies das últimas 5 partidas.
  - **Ameaças:** os counters da temporada (as derrotas) mais quem estava no time do outro nas derrotas recentes, com peso maior para as recentes e para o dano.
  - **Tipos que te castigam** e **buracos do time:** tipos de ataque que pegam 2 ou mais do time. A tabela de tipos é a da série, a mesma de `shared/tipo-efetividade.mjs` do jogo.
  - **Sugestões, de 3 sinais:**
    - 45%: quem ganha das suas ameaças no PvP inteiro, só com 20 ou mais confrontos e confiança n/(n+60);
    - 35%: a taxa no meta do seu rank, puxada para 50% com poucas partidas;
    - 20%: o encaixe de tipos (resiste aos golpes das ameaças, bate forte nelas, tapa os buracos).
  - O que já está no time fica de fora. Com orçamento, cada sugestão mostra o anúncio mais forte e o mais barato da loja que cabem nele.
- **Meta do rank:** os mais usados, a melhor taxa (500+ partidas) e os times dos 10 primeiros do ranking.
- **Busca de Pokémon:** o objetivo "PvP" ordena por 60% a nota de PvP da espécie (meta do high elo e, com o nick salvo, as suas ameaças) e 40% o poder do anúncio.

## Estrutura prevista

```
pokeidletracker/
  data/
    inbox/        # exportações novas
    processed/    # exportações já importadas
    market.db     # SQLite
  src/
    importer.py   # CSV/XLSX → SQLite, com deduplicação
    stats.py      # médias, janelas, variações
    app.py        # painel Streamlit
    fetch.py      # (fase 2) exportação automática
  PLANO.md
```

## Observação sobre a taxa
Uma venda a 130 gemas rendeu 110, ou seja, cerca de **15% de taxa**, o que não é pouco. Para quem compra para revender, o preço de venda precisa ser pelo menos ~18% maior que o de compra só para empatar (130 → ~153). O painel vai mostrar esse ponto de empate.

## O que já está confirmado
- **Taxa de 15%** sobre a venda. Fórmulas: líquido = preço × 0,85; empate na revenda = preço de compra ÷ 0,85.
- **A exportação traz todas as vendas do mercado**, não só as suas. Isso dá preços de mercado de verdade, e não só o seu histórico.
- **Duas moedas: coins de ouro e gemas.** Só as gemas podem ser sacadas em USDT.
  - Cada transação fica salva com a sua moeda, e os preços **nunca são misturados**: a média de um item em coins e a média em gemas são calculadas separadamente.
  - O painel mostra gemas por padrão e tem um seletor para ver coins. Se o mesmo item for vendido nas duas moedas, dá para estimar uma taxa de câmbio implícita entre coins e gemas, o que é útil para saber em qual moeda vale mais a pena vender.
- **Exportar tudo, sem filtros.** O importador separa tudo depois (item ou Pokémon, tipo de item, moeda). Assim nada fica de fora e as vendas de Pokémon já vão sendo guardadas desde agora para a Fase 4.

## O que a primeira planilha mostrou (07/11, 16:29 → 18:47)
- **Formato:** CSV com `;`, UTF-8, vírgula decimal. Colunas: Data, Tipo, Item, Quantidade, Moeda, Valor total, Valor unitário, Vendedor, Comprador e, só para Pokémon, Nível, Shiny, Nota, IV total, Potência, Qualidade.
- **Não há ID de transação e a data só vai até o minuto.** Linhas idênticas podem ser vendas diferentes de verdade (51 neste arquivo). O importador trata isso minuto a minuto. *(feito e testado)*
- **Volume:** 4.541 vendas de itens e 459 de Pokémon em ~2h20; em média 36 por minuto, com pico de 123.
- **Itens únicos com número de série** (`Common House #001706`, `Rare House #000098`, `Common Bicycle #001805`) são agrupados por tipo. Hoje: Common House ~1.600 gemas, Common Bicycle ~1.290, Rare House 14.500.
- **Preços em gemas agora (mediana, mínimo–máximo):** Bicycle Fragment 199 (146–225), Key Fragment 270 (202–388), Shiny Stone Fragment 115 (99–149), Mega Stone Fragment 120 (100–130). Uma semana antes, o mesmo fragmento saía a ~130.
- **Câmbio implícito:** em vários itens vendidos nas duas moedas, 1 gema ≈ **3,6 a 4,3 milhões de coins**.
- **Erros de digitação e vendas fora da curva existem:** Bronze Boss Token tem mediana de 3 gemas e uma venda a 837; mediana de 15,5M coins e uma a 2 coins. Bicycle Fragment teve uma venda a 2M coins contra uma mediana de 750M. As estatísticas usam **mediana** e marcam valores muito distantes dela como suspeitos, em vez de deixá-los distorcer a média.
- **Pokémon** já vêm com nível, shiny, nota, IV total, potência e qualidade, o que basta para a Fase 4.

## Investigação da Fase 2 (07/11)

### Termos de Uso (pokeidle.io/terms)
- **Automação é permitida de forma explícita** (seção 5, "Automação"), no jogo e no Mercado, desde que **não burle limites do jogo nem sobrecarregue o servidor**. Para nós isso significa: **1 export por hora, de um IP só**. Nada de proxy ou conexões extras para baixar mais vezes, o que seria "automação proibida" (seção 6, item 6: suspensão ou banimento).
- **Gema em dinheiro:** compra a US$ 0,01 e saque a **US$ 0,009** (spread de 10%). Saque mínimo de 1.000 gemas (US$ 9). Exemplo: um Bicycle Fragment a 199 gemas rende 199 × 0,85 × 0,009 ≈ **US$ 1,52** no bolso.
- **Comissões oficiais (seção 13):**
  - item vendido em gema: 15%; qualquer venda em Coins: 15% (a página inicial diz 10% em Coins, mas os Termos dizem 15%);
  - Pokémon vendido em gema: progressiva, como imposto de renda: 13% até 500, 10% de 501 a 5.000, 7,5% acima;
  - anúncio de Pokémon paga diária de 100.000 Coins (1 a 30 dias), mesmo se vender antes;
  - a comissão em gema é arredondada para cima (numa venda de 3 gemas, a comissão é 1).
- **Casa e bicicleta (seção 14):** Comum é **74,5%** (por isso a soma da tela dava 99,505%). E existe **upgrade: 5 iguais viram 1 da raridade seguinte, sem sorteio, até a Rara**. Com os anúncios de hoje o upgrade não compensa (5 × Bicicleta Comum 1.339 = 6.695 contra 2.500 da Incomum), mas ele define um teto: a Rara não deveria passar de 5 × o preço da Incomum por muito tempo.

### Como o export funciona por dentro
- Não é um link de download. O botão manda pela **conexão WebSocket do jogo** a mensagem `{t: 'csv.pedir', tipo: 'mercado', filtros}`, e o servidor responde `{t: 'csv', ok, mercado: {linhas, cortado}, esperaMs}`. **O CSV é montado no navegador** a partir dessas linhas em JSON.
- O limite de 1 por hora é aplicado no servidor ("uma por conexão" segundo o código), e a resposta já diz quanto falta para o próximo (`esperaMs`).
- **Login do socket:** `wss://pokeidle.io`, primeira mensagem `{t: 'hello', nick, token, delta: 1, dispositivo}`. O token fica no `localStorage` (`sessao`), vale 30 dias e o servidor manda um novo (`sessao.renovada`) depois da metade do prazo.
- **⚠ Uma conexão por conta:** se uma segunda conexão entra na mesma conta, o servidor derruba a anterior (código 4001) e a aba do jogo **para de jogar** até alguém clicar em "Jogar aqui". Ou seja, um coletor externo na sua conta principal mataria a sua hunt.

### O que cada fonte entrega
| Fonte | Mensagem | Conteúdo | Limite |
|---|---|---|---|
| Export (CSV) | `csv.pedir` → `csv` | 5.000 vendas em lista: `[em, tipo, descrição, qtd, moeda, bruto, vendedor, comprador, [nível, shiny, nota, iv, potência, qualidade]]`. **`em` vem em milissegundos** (o CSV corta no minuto). Não tem ID. | 1 por hora |
| Tabela de preços (tela) | `market.historicoGlobal` | 30 vendas por página, **com ID sequencial** (`id: 959912…`) e a ficha completa do Pokémon (IVs, stats, espécie, tipos). | uso normal da tela; **não** vamos paginar em massa para contornar o limite do export |
| Vitrine de itens | `market.itens` | Para **todos os itens de uma vez**: nº de anúncios, unidades à venda, menor preço em Coins e em gemas, e a **média de 7 dias** em cada moeda. Ex.: `70080` (Bicicleta Comum) 10 anúncios, mín. 1.339 gemas. | leitura leve que a tela faz sempre; 1 vez por hora é tranquilo |

Consequências:
- **Deduplicação fica quase perfeita:** com o horário em milissegundos, duas vendas idênticas no mesmo milissegundo são praticamente impossíveis. O algoritmo atual (por minuto, com contagem) continua valendo como rede de segurança.
- **Os anúncios entram de graça:** um snapshot de `market.itens` por hora já dá a série histórica de oferta (anúncios e preço mínimo) de todos os itens, inclusive Mítica e Lendária.
- Os itens vêm por **ID numérico**; falta montar a tabela ID → nome (ex.: 70040/70041/70043 = Casa Comum/Incomum/Mítica, 70080 a 70083 = Bicicleta Comum a Mítica).

### Robô coletor com conta separada (caminho atual)
O Tampermonkey não roda direito dentro do Idle Deck, então a coleta saiu do navegador: `src/robo.py` entra com uma **conta separada, só para coletar** (os Termos permitem 4 por pessoa e 4 conectadas por rede), faz uma rodada curta e desconecta.

- **Sessão contínua (desde 09/11):** `hello` → espera o `welcome` (aguenta a fila de login do gateway) e **fica conectado**:
  - `market.itens` (a vitrine) a cada minuto. Era 30 min até 08/11 e 15 min até 09/11; a vitrine atrasada atrapalhava a análise de venda, e é um pedido leve, como abrir a loja.
  - `csv.pedir` quando o jogo libera (1 por hora, pelo `esperaMs`/`restaMs`).
  - A loja de Pokémon a cada 3 h.

  Antes, cada rodada fazia login e desconectava. Com a vitrine de minuto em minuto, isso seria um login por minuto, então ficar conectado pesa menos para o servidor. Um ping a cada 25 s mantém a conexão.
  - Antes de cada pedido, o robô descarta o que chegou sem ser pedido, para não confundir uma atualização velha com a resposta.
  - Se a conexão cair, entra de novo depois de 1 min, dobrando a cada queda seguida até 10 min. A espera volta a 1 min depois de 10 min conectado.
  - 4001 (conta aberta em outro lugar) continua esperando 30 min.
  - A conta coletora agora fica online o tempo todo e conta no limite de 4 contas conectadas por rede.
- **Vitrine no banco:** os retratos de minuto ficam 3 dias. Depois, uma poda de hora em hora deixa só um a cada 15 min, a mesma resolução do histórico de antes. Sem a poda seriam ~50 mil linhas por dia. No `robo.log` aparece uma linha de vitrine a cada 15 min, não a cada minuto.
- Os nomes dos itens vêm do `items.json` público uma vez por dia.
- **Token:** fica em `config.local.json` (fora do controle de versão). O jogo renova o token depois de 15 dias (`sessao.renovada`) e o robô salva o novo sozinho.
- **Sessão tomada (4001):** se a conta coletora for aberta em outro lugar, o robô espera 30 min em vez de brigar pela sessão.
- **Recusas de conta** (token inválido, ban, rede bloqueada) param o robô com uma mensagem clara. Rede cheia faz ele tentar de novo mais tarde.
- **Fuso fixo em Brasília (UTC−3)**, para os minutos baterem com o CSV mesmo num sistema configurado em outro fuso.
- **Testado contra um servidor falso** que imita o jogo (export, vitrine, token renovado, recusa, 4001, token inválido e export repetido) e, desde 08/11, rodando contra o jogo de verdade.

#### Passo a passo
1. **Criar a conta coletora** no pokeidle.io, num navegador comum (Chrome), e aceitar os Termos no primeiro login.
2. **Copiar nick + token:** com o jogo aberto nessa conta, F12 → aba Console. Se o Chrome pedir, digite `allow pasting`. Depois rode:
   ```js
   copy(JSON.stringify((({nick, token}) => ({nick, token}))(JSON.parse(localStorage.sessao))))
   ```
   Isso copia uma linha com o nick e o token. **Não cole isso em lugar nenhum além do passo 3.**
3. **Salvar no PC:** `python src/robo.py --configurar`, colar a linha e teclar Enter.
4. **Fechar a aba do jogo dessa conta, sem clicar em "Sair"** (sair pode invalidar o token).
5. **Instalar a dependência** uma vez: `pip install -r requirements.txt`.
6. **Testar:** `python src/robo.py --uma-vez`. Depois deixar rodando com `iniciar.bat` (ícone na bandeja; log em `data/robo.log`).

#### Numa VM ou VPS: não permitido
A ideia era deixar o robô (e depois as contas que caçam) rodando 24h numa VM na nuvem. Em 09/11/2026 a equipe do jogo confirmou que **VPS não é permitido**, então tudo roda só no PC.

### Alternativa: userscript no Idle Deck (não funcionou por lá)
A ideia era aproveitar as contas que já ficam caçando no **Idle Deck** (um navegador para jogos idle), que aceita extensões da Chrome Web Store e scripts do GreasyFork/OpenUserJS. Por isso o coletor é um **userscript** dentro da aba do jogo, sem conta extra.

```
Idle Deck (abas do jogo, uma por conta)
  └─ userscript  ──(socket do próprio jogo)──>  csv.pedir / market.itens
        │ GM_xmlhttpRequest (a CSP do jogo bloqueia fetch para fora; o GM passa por fora dela)
        ▼
  python src/coletor.py  (http://127.0.0.1:8765)  ──>  data/market.db
```

- **Quem manda é o servidor local:** a cada minuto cada aba pergunta "é a minha vez?" (`/vez`). Só uma recebe "sim" por hora; as outras esperam. Se uma conta fechar, a outra assume.
- **Export:** respeita o `esperaMs`/`restaMs` que o jogo devolve, mais 30 s de folga. A resposta é interceptada para o jogo não baixar um .csv nem mostrar aviso a cada hora.
- **Vitrine:** a cada 30 min, um snapshot de `market.itens` (anúncios, mínimo e média de 7 dias de todos os itens). Quando você mesmo abre o mercado, esse retrato também é salvo.
- **Nomes dos itens:** `items.json` uma vez por dia; os IDs especiais (casas, bikes, fragmentos) ficam fixos no código.
- **Só o nick sai da página.** O token da sessão nunca é lido para fora.
- **Testado ao vivo (07/11, 19:20):** o script se conectou ao socket, mandou a vitrine (35 itens) e os nomes (420), e recebeu do jogo a recusa `csv.espera` (faltavam 29 min desde o export manual das 18:47), sem aviso nenhum aparecer no jogo. O export aceito ainda não foi testado ao vivo; o formato das linhas foi testado com dados simulados.

### Instalação
1. **Tampermonkey** (ou Violentmonkey) pela Chrome Web Store dentro do Idle Deck. O gerenciador de scripts precisa ter `GM_xmlhttpRequest`; se o do Idle Deck não tiver, o script avisa no console e não faz nada.
2. **Ligar o coletor no PC:** dois cliques em `extras/iniciar-coletor.bat` (deixe a janela aberta). Status em http://127.0.0.1:8765.
3. **Instalar o script:** com o coletor ligado, abrir `http://127.0.0.1:8765/pokeidle-coletor.user.js` no Idle Deck; o Tampermonkey oferece a instalação. Se o Idle Deck não deixar abrir esse endereço, criar um script novo no painel do Tampermonkey e colar o conteúdo de `src/userscript/pokeidle-coletor.user.js`.
   - Não precisa publicar nada no GreasyFork. Publicar deixaria o script público e não traz vantagem.
4. Recarregar as abas do jogo. Em até ~1 min o status mostra as contas em "abas_segundos_desde_contato".

Se o Tampermonkey não funcionar no Idle Deck, há um plano B sem `GM_xmlhttpRequest`: um script simples só pede o export no horário certo, o próprio jogo baixa o .csv, e o importador vigia a pasta de Downloads. Esse caminho perde os milissegundos e a vitrine.

## Estado atual
- [x] `src/importer.py`: CSV → `data/market.db`, deduplicando por minuto, com aviso de buraco entre exports. A primeira planilha já foi importada (5.000 vendas).
- [x] Investigar como o botão de exportar funciona (Fase 2).
- [x] Coletor: `src/coletor.py` (servidor local) + `src/userscript/pokeidle-coletor.user.js`, com vendas, vitrine e nomes de itens. Testado com dados simulados e, em parte, ao vivo.
- [x] Userscript no Idle Deck: o Tampermonkey não funciona lá; fica como alternativa.
- [x] Robô coletor com conta separada (`src/robo.py`), testado contra um servidor falso.
- [x] Conta coletora configurada. **Primeiro export real em 08/11 às 11:48:** 5.000 vendas (10:01 → 11:48, todas com milissegundos) e o primeiro snapshot da vitrine. Há um buraco registrado entre 07/11 18:47 e 08/11 10:01, que é a noite antes do robô.
  - Domingo de manhã, 5.000 vendas cobriram só **1h47**. Com export de hora em hora sobra ~47 min de sobreposição; fica de olho em `buracos` no status.
  - Vitrine sem nome para os IDs 70017, 70090 e 70095 (falta identificar).
  - O mapeamento 70014 = Mega Stone Fragment ficou em dúvida: média de 7 dias de 61 contra mínimo de 123.
- [x] ~~Fase 5: robô, painel e contas numa VM na nuvem.~~ Descartada: a equipe do jogo confirmou que VPS não é permitido.
- [x] **Segundo plano + inicialização com o Windows:** `src/bandeja.py` roda o robô e o painel como processos ocultos (sem janelas na barra de tarefas) e põe uma pokébola na bandeja, perto do relógio. Pelo menu do ícone dá para abrir o painel, ver o log, reiniciar cada um, ligar/desligar a inicialização com o Windows e sair. Se um dos dois cair, a bandeja religa (espera 30 s, depois mais a cada queda seguida, até 10 min). Código de saída 3 quer dizer "não adianta religar": é o caso de sessão recusada, robô duplicado ou porta 8770 ocupada. O atalho fica em `shell:startup\PokeIdle Tracker.lnk` (criado com `python src\bandeja.py --instalar` e apagado com `--remover`). Um robô por PC: um mutex do Windows impede dois robôs na mesma conta. Logs: `data/robo.log`, `data/robo.erros.log` (tracebacks), `data/painel.log`, `data/bandeja.log`.
- [x] **Janelinha de status:** `src/mini.py` abre com o clique esquerdo na pokébola (ou "Status agora" no menu). É uma janela pequena, sempre por cima e sem botão na barra de tarefas, no canto acima do relógio. Mostra:
  - se o robô e o painel estão ligados;
  - o que o robô está fazendo agora (entrando no jogo, export, vitrine, loja de Pokémon, alertas ou esperando);
  - durante a leitura da loja, uma barra de progresso com anúncios lidos/total, passada, página e tempo restante;
  - os horários da próxima vitrine, export e loja;
  - a última linha do log.
  O robô publica o estado em `data/robo_agora.json` (função `agora()` em robo.py); os horários saem do banco (mesma conta de `robo.proximos_horarios`). Fecha com Esc ou no X.
- [x] **Painel web (Fase 1)** em estilo pixel art: `src/painel.py` (API + servidor, só em 127.0.0.1:8770) e `src/painel/` (HTML/CSS/JS sem dependências; gráficos em SVG próprios). Abrir com `iniciar.bat` (ou pelo ícone na bandeja). Troquei o Streamlit por uma página própria para conseguir o visual do jogo.
  - **Mercado:** lista de itens com mediana de 24h, variação, nº de anúncios e mini gráfico. No detalhe: mediana, média por unidade, mín/máx, vendas, menor anúncio, média 7d do jogo; gráfico de preço (mediana + faixa mín–máx + menor anúncio) com tooltip; volume num gráfico separado; janelas de 24h/7d/30d/tudo; calculadora de taxa (líquido, US$, ponto de empate) e últimas vendas. Vendas fora de [mediana÷4, mediana×4] são marcadas como suspeitas e ficam fora das estatísticas.
  - **Montagem:** valor esperado de casa e bicicleta, com a fonte de preço escolhível (nossas vendas → média do jogo → anúncio), "sem a Mítica" e upgrade 5→1.
  - **Pokémon:** lista crua das vendas com filtros (espécie, moeda, shiny), base da Fase 4.
  - **Menu Tipo/Categoria** como o do mercado do jogo: Casas, Bicicletas, Fragmentos, Pedras, Boss Tokens, Tickets, TMs (e Outros, se aparecer algo sem categoria).
  - **Ícones do próprio jogo**, carregados direto de pokeidle.io pelo navegador (nada copiado para o projeto): itens comuns pelo `icon` do `items.json` (guardado em `itens.icone`), casas, bicicletas e fragmentos por `/img/itens/*.png`, gema e coin pelos ícones das moedas. Fallback: a bolsa do jogo. Nenhuma imagem do jogo fica no repositório: o navegador de quem abre o painel busca direto do site.
  - IDs identificados pelo preço: 70017 = Shiny Egg Fragment, 70090 = Mystic Ticket.
  - Gráfico: paleta validada para o fundo escuro (#d84e98 vendas, #b8872a anúncio, incluindo daltonismo), um eixo só, linha interrompida onde falta coleta.
  - **Cuidado na Montagem:** a "média 7d do jogo" às vezes é bem menor que as nossas medianas (Mega Stone Fragment: 61 contra 120), então pode não ser calculada do mesmo jeito. Misturar as duas fontes pode distorcer o valor esperado.

## Fragmentos × item pronto
**Regra confirmada:** sempre **10 fragmentos = 1 item** (bicicleta, casa, pedra shiny, pedra de mega).

O painel vai ter uma tela comparando, para cada par: 10 × mediana do fragmento, mediana do item pronto e o líquido de cada caminho já com os 15% de taxa.

Na primeira planilha (gemas, mediana):

**Pares confirmados:**

| Fragmento | Item montado | Sorteio de raridade? |
|---|---|---|
| Bicycle Fragment | Bicicleta | sim |
| Key Fragment | Casa | sim (mesmas chances da bicicleta) |
| Shiny Stone Fragment | Pedra shiny | não; o tipo da pedra é escolhido na montagem |
| Mega Stone Fragment | Pedra de mega | não; o tipo é escolhido na montagem |
| Mega Shiny Stone Fragment | Pedra mega shiny | não; o tipo é escolhido na montagem |

Nas pedras não tem sorteio, então a conta é direta: 10 × fragmento contra o preço da pedra do tipo que você escolheria montar.

### Sorteio de raridade (casa e bicicleta)

| Raridade | Chance | Bônus da casa |
|---|---|---|
| Comum (Common) | 74% | 1 Pokémon, 25% do XP da hunt |
| Incomum (Uncommon) | 20% | 1 Pokémon, 40% do XP |
| Rara (Rare) | 5% | 1 Pokémon, 75% do XP |
| Mítica (Mythic) | 0,5% | 1 Pokémon, 100% do XP |
| Lendária (Legendary) | 0,005% | 2 Pokémon, 100% do XP |

As chances somam 99,505%, e não 100%. Ou o jogo arredonda, ou falta alguma faixa. O cálculo usa os valores como estão.

### Montar ou vender os fragmentos? (valor esperado)
O certo é comparar **o valor esperado de montar** (soma de chance × preço de cada raridade) com **o que os 10 fragmentos valem no mercado**. Os dois caminhos pagam os mesmos 15% na venda, então dá para comparar os valores brutos.

Com a primeira planilha (gemas, mediana):

| | Casa (Key) | Bicicleta |
|---|---|---|
| 10 fragmentos valem | 10 × 270 = **2.700** | 10 × 199 = **1.990** |
| Parte conhecida do valor esperado | 74% × 1.598 + 5% × 14.500 = **1.908** | 74% × 1.290 = **955** |
| Quanto Incomum + Rara + Mítica + Lendária precisam somar para empatar | **792** | **1.035** |
| Preços ainda sem venda no período | Incomum, Mítica, Lendária | Incomum, Rara, Mítica, Lendária |

Leitura:
- **Casa:** se a Incomum valer uns 4.000 gemas (20% × 4.000 = 800), montar já empata. Ou seja, os fragmentos parecem estar com preço justo para um sorteio, o mercado não está errado.
- **Bicicleta:** ainda não dá para dizer; falta o preço de todas as raridades acima de Comum.
- **Risco:** 74% das vezes sai Comum, e você termina com ~1.300 a 1.600 gemas em vez de 2.000 a 2.700. Montar é uma aposta que só se paga na média, depois de muitas montagens.
- **A casa também tem uso no jogo** (Pokémon extra + XP da hunt). Se você for usá-la, e não vender, o valor dela para você é maior que o preço de mercado.

### Atualização com os anúncios do mercado (07/11, menor preço anunciado, em gemas)

| Raridade | Chance | Bicicleta | Casa |
|---|---|---|---|
| Comum | 74% | 1.339 (10 anúncios) | 1.550 (17 anúncios) |
| Incomum | 20% | 2.500 (7) | 3.750 (5) |
| Rara | 5% | 7.499 (3) | sem anúncio; última venda 14.500 |
| Mítica | 0,5% | 40.000 (1) | 60.000 (1) |
| Lendária | 0,005% | sem anúncio | sem anúncio |
| **Valor esperado de montar** | | **2.066** | **2.922** |
| **10 fragmentos valem** | | **1.990** | **2.700** |
| **Vantagem de montar** | | **+3,8%** | **+8,2%** |
| **Vantagem sem contar a Mítica** | | **−6,2%** | **−2,9%** |

Leitura:
- No papel, montar tem uma vantagem pequena: +4% na bicicleta, +8% na casa.
- **Essa vantagem vem toda da Mítica.** Sem ela, montar dá prejuízo nos dois casos. E a Mítica é 1 montagem em 200, com 1 único anúncio de cada; não há prova de que alguém compre a 40.000 ou 60.000.
- O menor anúncio é o preço pedido, não o preço de venda. Para vender rápido é preciso anunciar um pouco abaixo dele, e isso come parte da margem.
- **Conclusão por enquanto:** os fragmentos estão com preço praticamente justo. Montar só compensa como aposta repetida muitas vezes, ou se você for usar a casa.

**No painel:** essa tabela é recalculada sozinha, com as medianas das vendas dos últimos 7 dias de cada raridade e com os anúncios atuais lado a lado. Raridades com poucas vendas aparecem como "dados insuficientes".

### Anúncios abertos como segunda fonte de dados
O export só traz **vendas concluídas**. A tela do mercado mostra também os **anúncios abertos** (menor preço e quantidade de anúncios), que é o lado da oferta. Juntar os dois permite:
- ver a diferença entre o menor preço pedido e o preço das últimas vendas
- perceber quando muitos anúncios aparecem de uma vez (preço deve cair) ou quando somem (preço deve subir)
- dar preço a itens que quase nunca vendem (Mítica, Lendária)

Na investigação da Fase 2, ver também se essa tela vem de uma API que dá para consultar.

**Nomes:** a tela do jogo usa português (Bicicleta Comum, Casa Mítica) e o export usa inglês (Common Bicycle, Rare House). O sistema precisa de uma tabela de tradução entre os dois.

## Visual do jogo e menu da bandeja (10/11)
- **Fonte:** as fontes pixeladas (VT323 e Press Start 2P) ficavam pouco legíveis em várias escalas. O CSS público do jogo mostra que ele **não usa fonte pixelada**: o texto é Segoe UI e títulos, botões e números são Tahoma negrito com contorno escuro. O ar de pixel art vem das molduras. O painel passou a usar as mesmas fontes, que já vêm no Windows, e não baixa mais nada do Google Fonts.
- **Visual:** o painel copia as três peças do jogo (quadro de madeira, botão roxo ou de madeira, vão escuro), com as mesmas cores e o fundo xadrez azul.
- **Bandeja como a Steam:** duplo clique abre o painel, um clique abre o status e o botão direito abre um menu próprio, desenhado no visual do jogo, no lugar do menu cinza do Windows. O menu cinza continua como reserva, se o próprio falhar.

## Força de caça na busca de Pokémon (10/11)
Uma calculadora da comunidade ("vale a pena comprar?") simula a caça nível a nível com os módulos públicos do jogo (`shared/*.mjs`) e compara o XP por hora de dois Pokémon. Lendo esses módulos:
- **O ⚔ do jogo não mede força de caça.** Ele soma os seis atributos numa escala de log: o dobro de ATK dá ~30% a mais de ⚔. Exemplo nos nossos dados: um Scizor P5 Nv 100 tem ATK 488 e ⚔ 518; um Dragonite P2 Nv 100, ATK 241 e ⚔ 403.
- **O que decide a caça é o dano por golpe:** `(2·nível/5 + 2) × ATK ou SP.ATK`, na fórmula de dano do jogo. A busca ganhou o índice de caça (coluna "Caça") e o objetivo "caçar e upar". O índice passou a ser a força do "equilibrado" e do "mais por gema". Com o ⚔ por preço, o "mais por gema" premiava os baratos fracos. O ⚔ ficou só no objetivo "forte", como a régua do ranking.
- **Confirmações para o preço justo:** a nota é por espécie, e o Mercado só aceita nota ≥ 3,5 e nível ≥ 50 (shiny, P5 e lendário passam livres), que é onde começam as faixas de nota do modelo. O shiny só se anuncia em gemas.
- **Ficou de fora, por ora:** simular a caça inteira (mapas, HP e defesa dos selvagens, recargas e tempo morto por abate), como faz a calculadora. Seria o passo seguinte para comparar "o meu Pokémon de agora contra um candidato".
- **Bug achado no caminho:** uma espécie cujas vendas saíam todas como fora da curva no 2º ajuste do modelo derrubava a busca com erro (KeyError).

## XP por hora na busca de Pokémon (10/11)
Simular a caça inteira, como a calculadora da comunidade faz, leva segundos por Pokémon. Isso não serve para ordenar a loja. A busca ganhou um motor próprio (`analise/caca.py`) com três atalhos:
- só o nível de agora;
- uma estimativa fechada em todas as hunts (cada golpe uma vez por recarga, a Investida a cada 2 s);
- a mini-luta só nas 8 melhores estimativas.

O custo ficou em ~5 ms por Pokémon. Na busca, um funil de 200 (pelo índice de caça) e um cache deixam a lista em ~1 s na primeira vez e ~0,25 s depois.

O que a validação ensinou:
- **Golpes:** sem os golpes de assinatura (poder 600) e os das planilhas de balanceamento, o XP/h saía até 50% abaixo. O jogo injeta os dois no cliente, e o `creatures.json` sozinho não traz.
- **Limite de golpes por abate:** precisa ser folgado. Abaixo do nível 150 o XP do abate cresce com o quadrado do nível, e um Pokémon fraco rende mais numa hunt alta de luta longa.
- **Rolagens de HP:** 4 rolagens enviesavam o resultado (o golpe de 60 s pronto no 1º abate pesava 1 em 4). Com 16 ficou bom.
- **Resultado:** contra a calculadora, a mesma hunt em 6 de 6 casos, com o XP/h entre −15% e +17%. O ponto fixo do tempo morto melhorava pouco e custava 1,7×, então ficou de fora.
- **Outra lentidão achada no caminho:** a busca de Pokémon refazia o modelo de preço justo (~3 s) em toda chamada. Agora ele fica em memória até entrar venda nova.

## Pokémon ponte para levar gemas entre contas (11/11)
O jogo não tem troca entre jogadores. O caminho permitido: a conta que vai receber compra um Pokémon no piso do mercado em coins, anuncia em gemas pelo valor a transferir (um preço que ninguém mais paga num Pokémon de piso) e a outra conta compra logo em seguida. A busca ganhou o objetivo "ponte".
- **Candidatos:** até 15% acima do piso, que é a mediana dos 10 anúncios ativos mais baratos. No teste com a loja real, o menor anúncio em coins era um isolado a 150 mil, com o bloco do piso em 55-60 mi (~100 anúncios): usar o menor deixava o bloco todo de fora. Com a mediana, 15% pega esse bloco sem chegar nos Pokémon caros. Um percentil foi descartado porque depende do tamanho da loja inteira (o p5 de 5 mil anúncios já sai do piso). Se um filtro deixar o piso com poucos anúncios, o teto sobe até o 30º mais barato, sem passar de 1,5× o piso.
- **Ordem:** revender um Pokémon de piso não sai (há centenas iguais), então ele fica na conta que mandou as gemas e vai para o PvP dela. Por isso o mais decente para PvP primeiro, com a mesma conta do objetivo `pvp` (nota da espécie 60% e o indivíduo 40%; ver a seção seguinte) e o índice de caça e o preço como desempate. Se o Tracker cair, a ponte ainda funciona pelo ⚔.
- **Custo:** comissão progressiva de Pokémon em gemas + o Pokémon pelo câmbio do mercado + a diária de 100 mil coins do anúncio. O Pokémon e a diária são fixos, então, em proporção, a ponte sai mais barata em valores grandes.

## IVs individuais na busca e no PvP (11/11)
A soma dos IVs, e o ⚔ que soma os seis stats, esconde um Pokémon "decente em tudo" com o ataque ou o SPD horrível. No PvP e na caça, esses dois decidem a luta.
- **Lado de ataque pela espécie:** `lado_fisico` olha os golpes do catálogo já liberados no nível, cada um pesando poder ÷ recarga. Daí sai físico, especial ou misto. Antes, o índice de caça usava o maior entre ATK e SP.ATK do próprio Pokémon, o que erra numa espécie de golpes especiais com ATK alto (só a Investida é física).
- **Índice de caça com SPD:** × a cadência do IV de SPD (o intervalo e a recarga da Investida caem 10 ms por IV), normalizada para 1 no IV 16: ~0,9 no IV 1 e ~1,14 no IV 32. O XP/h já fazia a conta exata; o índice é a aproximação que ordena "caçar", "equilibrado", "custo" e o funil do "xp".
- **Nota dos IVs (0 a 10):** 40% o IV do ataque da espécie, 30% o de SPD e 10% cada HP, DEF e SP.DEF; o ataque que a espécie não usa não conta. O ataque pesa mais porque entra no stat como 2·IV (~+40% de dano de IV 1 a 32 numa espécie de base 100); o SPD vem logo atrás porque muda quantas vezes o Pokémon bate (~1/3 a mais). Um IV de ataque ou SPD abaixo de 11 tira até 40% da nota (IV 1 tira 40%, IV 10 tira 4%), e dois horríveis castigam os dois.
- **Onde pesa:** no `pvp` e na `ponte`, o indivíduo (40%) virou 15% ⚔ e 25% nota dos IVs; a espécie continua 60%. Na aba PvP, "o mais forte" da loja virou "o melhor": 40% ⚔ e 60% IVs dentro da espécie. A coluna IV da busca mostra a soma e, embaixo, o IV de ataque e o de SPD (em vermelho quando horríveis).

## Perguntas em aberto
- Os nomes no export para as outras raridades devem ser `Uncommon`, `Mythic` e `Legendary` (só vimos `Common` e `Rare`). Isso se confirma quando aparecerem vendas.
