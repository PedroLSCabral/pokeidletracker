# Arquitetura do PokeIdle Tracker

Este é o mapa técnico do projeto: onde está cada coisa, o que cada módulo faz, como os processos
conversam, o formato do banco e das APIs, e como fazer as mudanças mais comuns. Ele serve para
qualquer pessoa (ou IA) que vá mexer no código, para não ter que redescobrir o projeto do zero.

- **[`docs/PLANO.md`](PLANO.md)** é o diário: o porquê das decisões, as descobertas sobre o jogo, na ordem em que aconteceram.
- **[`CLAUDE.md`](../CLAUDE.md)** é o resumo de bolso, com as regras que não podem ser quebradas.
- **Este arquivo** descreve o **estado atual**. Quem mudar a estrutura, um módulo, uma rota ou uma tabela atualiza este arquivo no mesmo commit.

---

## 1. Visão geral

O pokeidle.io é um jogo idle de Pokémon com mercado de dinheiro real: as **gemas** podem ser sacadas
(a ~US$ 0,009 cada) e os **coins** são a moeda de jogo. O projeto:

1. **coleta** o mercado com uma conta separada (o robô): as vendas, a vitrine de itens e a loja de Pokémon;
2. **guarda** tudo num SQLite local (`data/market.db`);
3. **analisa** esses dados: preços, revenda, alertas, preço justo de Pokémon, quando e por quanto vender e PvP;
4. **mostra** num painel web local com o visual do jogo (`http://127.0.0.1:8770`) e avisa por Windows, Discord ou Telegram.

```
                       ┌─────────────────────── PC (Windows) ────────────────────────┐
 pokeidle.io           │                                                             │
 ┌──────────────┐  WS  │  bandeja.py  (ícone na bandeja; liga e vigia os dois abaixo) │
 │ socket do    │◄────►│   ├─ robo.py    sessão contínua no jogo → grava no banco      │
 │ jogo         │      │   └─ painel.py  servidor HTTP 127.0.0.1:8770 (API + página)   │
 └──────────────┘      │  mini.py     janelinha de status (um clique no ícone)         │
 ┌──────────────┐ HTTP │                                                             │
 │ /tracker/api │◄─────│  analise/pvp.py (pelo painel e pelo robô, sem login)          │
 └──────────────┘      │            data/market.db  ◄── todos leem/gravam aqui        │
                       └─────────────────────────────────────────────────────────────┘
```

Todo o código é Python 3.12+ e só depende de `websockets` (robô) e `pystray` + `pillow` (ícone).
O painel e a página não têm dependências: são HTML, CSS e JS puros, com gráficos em SVG próprio.

---

## 2. Estrutura de pastas

```
pokeidletracker/
├─ iniciar.bat              liga tudo (pythonw src\bandeja.py --abrir), sem janela de console
├─ requirements.txt         websockets, pystray, pillow
├─ README.md                apresentação e como usar
├─ CLAUDE.md                guia rápido para quem vai mexer no código (regras e atalhos)
├─ docs/
│  ├─ ARQUITETURA.md        este arquivo
│  └─ PLANO.md              diário do projeto (decisões e descobertas, em ordem)
├─ src/
│  ├─ bandeja.py            PROGRAMA: ícone na bandeja, supervisor do robô e do painel
│  ├─ robo.py               PROGRAMA: robô coletor (socket do jogo)
│  ├─ painel.py             PROGRAMA: servidor do painel (API JSON + arquivos de web/)
│  ├─ mini.py               PROGRAMA: janelinha de status (tkinter)
│  ├─ menu_bandeja.py       menu do botão direito no visual do jogo (Tk numa thread da bandeja)
│  ├─ tema.py               cores, fontes, moldura e pokébola das janelas Tk e do ícone
│  ├─ caminhos.py           todas as pastas e arquivos do projeto (RAIZ, DADOS, BANCO, CONFIG, WEB…)
│  ├─ notificar.py          avisos: Windows, Discord, Telegram
│  ├─ coleta/               o que GRAVA no banco
│  │  ├─ importer.py        esquema do SQLite, CSV/JSON do export, deduplicação, connect()
│  │  ├─ coletor.py         gravação compartilhada (vendas, vitrine, itens), agenda (tabela coleta), poda
│  │  └─ lojapk.py          tabelas e gravação da loja de Pokémon
│  ├─ analise/              o que LÊ o banco e calcula
│  │  ├─ sinais.py          revenda, barato/caro, liquidez, regras e disparo de alertas
│  │  ├─ venda.py           botão "vender": moeda, preço e momento
│  │  ├─ pokemon.py         preço justo de Pokémon, busca por orçamento, padrões do mercado
│  │  ├─ caca.py            XP por hora de caça de um Pokémon (motor rápido) e os dados do jogo que ele usa
│  │  └─ pvp.py             aba PvP (Tracker público do jogo)
│  └─ web/                  a página do painel
│     ├─ index.html         estrutura das abas e janelas
│     ├─ app.js             toda a lógica da página (uma seção por aba)
│     └─ app.css            visual do jogo (tokens de cor e fontes em :root)
├─ testes/
│  └─ teste_robo_sessao.py  robô contra um jogo falso (sessão, queda, vitrine, poda)
├─ legado/                  primeira tentativa de coleta: userscript no navegador (não roda no Idle Deck)
│  ├─ userscript/pokeidle-coletor.user.js
│  └─ iniciar-coletor.bat   liga o servidor do userscript (src/coleta/coletor.py, porta 8765)
├─ .claude/launch.json      cópia do painel na porta 8771, para testar sem mexer no que está rodando
├─ config.local.json        (fora do git) nick + token da conta coletora, canais de alerta
└─ data/                    (fora do git) market.db, logs, robo_agora.json, inbox/ do importador e jogo/
                            (catalogo.json e welcome-dados.json, para o XP/h)
```

**Como os imports funcionam.** Os quatro programas ficam em `src/` e põem `src/` no `sys.path`. Os
módulos importam por pacote: `from coleta import importer`, `from analise import sinais`,
`import caminhos`. Os módulos de `coleta/` que também rodam como script (`importer.py`, `coletor.py`)
têm uma guarda no topo que põe `src/` no caminho quando são executados direto.

**Por que os programas ficam na raiz de `src/`.** O atalho de inicialização do Windows aponta para
`src\bandeja.py`, e a bandeja liga `src\robo.py` e `src\painel.py` pelo nome. Mover um deles quebra a
inicialização com o Windows. Se for preciso mover, rode `python src/bandeja.py --instalar` de novo.

---

## 3. Processos e ciclo de vida

### `bandeja.py`: o supervisor
- **Como liga:** pelo `iniciar.bat`, pelo atalho em `shell:startup\PokeIdle Tracker.lnk` (que roda `pythonw src\bandeja.py`) ou por `python src/bandeja.py`.
- **Uma bandeja só:** o mutex `Local\PokeIdleTrackerBandeja` garante isso. Uma segunda só abre o navegador, e só se foi chamada com `--abrir`.
- **Liga o robô e o painel antes de importar o `pystray`.** Assim, se a biblioteca do ícone faltar, os dois rodam mesmo assim e aparece um aviso.
- **Os filhos (`class Filho`) rodam como `python.exe` com `CREATE_NO_WINDOW`,** sem janela nem botão na barra de tarefas.
  - O robô escreve o próprio `data/robo.log`; os tracebacks dele vão para `data/robo.erros.log`.
  - O painel escreve em `data/painel.log`.
  - A própria bandeja escreve em `data/bandeja.log`.
  - Um log com mais de 2 MB vira `.old` na próxima vez que o processo liga.
- **Quando um filho cai:**
  - com **código 3** (fatal), não religa e mostra uma notificação. É o caso de sessão recusada, robô duplicado ou porta ocupada;
  - com qualquer outro código, religa depois de 30 s. A espera dobra a cada queda seguida até 10 min e volta a 30 s depois de 10 min de pé.
- **Cliques no ícone, como na Steam** (`classe_icone()`, que estende o `pystray.Icon` e troca o `_on_notify`):
  - **duplo clique** abre o painel no navegador;
  - **um clique** abre o `mini.py`. Ele espera o tempo de duplo clique do Windows (`GetDoubleClickTime`) antes de agir, para um duplo clique não abrir as duas coisas;
  - **botão direito** abre o menu no visual do jogo (`menu_bandeja.py`).
- **Menu do botão direito:**
  - no topo, o estado do robô (com a fase de `robo_agora.json`), do painel e a hora do último registro;
  - Abrir painel e Status agora;
  - Ver log do robô e Abrir pasta de dados;
  - Reiniciar robô e Reiniciar painel;
  - Ligar junto com o Windows (cria ou apaga o atalho);
  - Sair.
- **Menu cinza do Windows:** o mesmo menu também existe como `pystray.Menu`. Ele só aparece se o menu próprio não abrir (sem Tk, ou um erro ao montar). O motivo vai para `data/bandeja.log`.
- **DPI:** a bandeja chama `SetProcessDpiAwareness(1)`, para o menu sair nítido em telas com escala.
- **Linha de comando:** `--instalar` e `--remover` cuidam do atalho de inicialização; `--abrir` abre o painel no navegador.

### `robo.py`: o coletor
- **Um robô por PC:** o mutex `Local\PokeIdleTrackerRobo` impede dois. Dois robôs na mesma conta se derrubam com o código 4001; um robô duplicado sai com código 3.
- **Sessão contínua** (`sessao()`): conecta em `wss://pokeidle.io`, manda `hello`, espera o `welcome` e **fica conectado**. A cada volta do laço:
  1. `tarefas_locais()`: os nomes dos itens (1 vez por dia), a poda da vitrine (1 vez por hora), a pré-carga do PvP (a cada 6 h, numa thread) e o catálogo de espécies do jogo (1 vez por dia, numa thread, `caca.baixar_catalogo`).
  2. Vê o que está na hora (`proximas_tarefas()`): o export (quando o jogo libera), a vitrine (a cada minuto) e a loja de Pokémon (a cada 3 h).
  3. Faz cada uma: `pedir_export()`, `ler_vitrine()`, `varrer_loja_pokemon()`. Depois, `checar_alertas()`.
  4. Dorme até a próxima tarefa (no mínimo 1 s, no máximo 10 min). Um ping a cada 25 s mantém a conexão viva.
- **Welcome:** ao entrar, `caca.guardar_welcome()` tira dele as hunts, as constantes de caça e a tabela de tipos e grava em `data/jogo/welcome-dados.json` (o estado da conta não é guardado). Grava também `welcome-esqueleto.json`, só com as chaves, para conferir o formato quando o jogo mudar.
- **`Sessao`:**
  - um leitor em segundo plano filtra as mensagens que interessam e as põe numa fila;
  - `pedir()` descarta o que chegou sem ser pedido, envia e espera a resposta que satisfaz a condição;
  - o prazo estica enquanto o gateway manda `vivo` (fila de login);
  - um `sessao.renovada` com token novo é salvo no `config.local.json`.
- **Reconexão** (`rodar()`):
  - conexão fechada pelo jogo: espera 1 min, dobrando até 10 min, e zera depois de 10 min conectado;
  - **4001** (a conta foi aberta em outro lugar): espera 30 min, sem disputar a sessão;
  - qualquer outro erro: 5 min;
  - recusas fatais (`RECUSAS_FATAIS`: ban, token inválido…) param o robô com código 3.
- **Estado ao vivo:** `agora(**campos)` grava `data/robo_agora.json` de forma atômica. Os campos são fase, detalhe, progresso da loja, erro e `acordar_ms`. É isso que o `mini.py` lê.
- **Linha de comando:**
  - `--configurar` cola o JSON com nick e token;
  - `--uma-vez` faz uma volta só, para teste.

### `painel.py`: o servidor do painel
- **Servidor:** `ThreadingHTTPServer` em `127.0.0.1:8770`. `--porta N` troca a porta (a cópia de teste usa 8771).
- **GET:**
  - `/api/*` devolve JSON (ver a seção 7);
  - o resto serve os arquivos de `src/web/`.
- **POST:** só com `Content-Type: application/json`. Sem a permissão CORS, um site de fora não consegue mandar esse tipo de pedido para 127.0.0.1, então nenhuma página externa mexe nas regras.
- **Uma conexão SQLite por pedido** (`importer.connect()`).
- **Erros:**
  - `pvp.ErroPvP` vira 400 com a mensagem;
  - qualquer outra exceção vira 500 com `repr`.
- **Porta já em uso:** sai com código 3 (`allow_reuse_address = False`). No Windows, sem isso, dois servidores dividiriam a porta.

### `mini.py`: a janelinha de status
- **Janela:** tkinter, `-toolwindow` (sem botão na barra) e `-topmost`, no canto inferior direito da área de trabalho.
- **Uma janela só:** o mutex `Local\PokeIdleTrackerMini`. Uma segunda chamada traz a janela que já existe para a frente (`FindWindowW` pelo título).
- **O que mostra:**
  - um LED do robô (pelo mutex dele) e um do painel (por uma conexão na porta 8770);
  - a fase atual, lida de `robo_agora.json`, com barra de progresso na leitura da loja;
  - os próximos horários, lidos da tabela `coleta` só para leitura, com as mesmas contas do robô;
  - a última linha do `robo.log`.

### `menu_bandeja.py`: o menu do botão direito
- **`MenuBandeja`** sobe um `tk.Tk()` escondido numa thread própria da bandeja. `mostrar(x, y, estado, itens)` pode ser chamado de qualquer thread: o pedido entra numa fila que o Tk lê a cada 60 ms.
- **Itens:** `Item(texto, acao, ativo, marcado, destaque)`; `SEPARADOR` é `None`. Cada ação roda numa thread nova, para o menu não travar enquanto um processo reinicia.
- **Janela:** `Toplevel` sem moldura do Windows (`overrideredirect`) e por cima de tudo, com o canto de baixo à direita no mouse, sem sair da área útil do monitor (`MonitorFromPoint`).
- **Fecha** com Esc, ao perder o foco ou com um clique fora. O clique fora é vigiado com `GetAsyncKeyState`, porque o `FocusOut` nem sempre chega numa janela sem moldura.
- **Visual:** quadro de madeira, título com contorno e dois vãos (estado e ações). A linha sob o mouse fica roxa.

### `tema.py`: o visual das janelas Tk
- As cores do jogo (as mesmas do `app.css`), as fontes (`TEXTO` = Segoe UI, `TITULO` = Tahoma) e `FASES` (texto e cor de cada fase do robô).
- **Peças:** `moldura()` (quadro de madeira), `vao()` (área escura com filete), `titulo_contornado()` (Tahoma negrito branco com contorno, desenhado num `Canvas`) e `desenhar_pokebola()` (o ícone da bandeja, em pixel art 16×16).

---

## 4. Fluxo dos dados

| Origem (no jogo) | Quem pede | Quem grava | Tabela | Frequência |
|---|---|---|---|---|
| `csv.pedir` (export de vendas) | `robo.pedir_export` | `coletor.receber_vendas` → `importer.import_rows` | `trades`, `imports` | quando o jogo libera (1/h) |
| `market.itens` (vitrine) | `robo.ler_vitrine` | `coletor.receber_vitrine` | `vitrine` | a cada minuto |
| `market.listar` (loja de Pokémon) | `robo.varrer_loja_pokemon` | `lojapk.gravar` / `lojapk.finalizar` | `pk_anuncios`, `pk_varreduras` | a cada 3 h |
| `items.json` (público, HTTP) | `robo.baixar_itens` | `coletor.receber_itens` | `itens` | 1/dia |
| Tracker `/tracker/api/*` (HTTP) | `pvp.tracker` | `pvp.tracker` (cache) | `pvp_cache` | sob demanda, com cache; pré-carga a cada 6 h |

Os alertas (`sinais.avaliar`) rodam depois de cada coleta e gravam em `alertas_log`. O painel
consulta `/api/alertas/novos` a cada 30 s para tocar o som.

---

## 5. Banco de dados (`data/market.db`)

Cada módulo cria as suas tabelas com `CREATE TABLE IF NOT EXISTS`. Não há migração separada: as
colunas novas entram com `ALTER TABLE` dentro de `importer.connect()`.

| Tabela | Criada em | Para quê |
|---|---|---|
| `trades` | importer | Cada venda: `ts` ('YYYY-MM-DD HH:MM', horário de Brasília), `ts_ms` (exato, quando vem do robô), `kind` ('item' ou 'pokemon'), `name`, `base_name` (agrupável: "Common House", "Numel"), `serial`, `qty`, `currency` ('gems' ou 'coins'), `total`, `unit_price`, `seller`, `buyer`. Para Pokémon também `level`, `shiny`, `nota`, `iv_total`, `potencia`, `qualidade`. |
| `imports` | importer | Um registro por importação, com `gap_before = 1` quando pode ter faltado venda entre um export e outro. |
| `vitrine` | importer | Retrato da vitrine de itens, chave (`snap_ms`, `item_id`): `anuncios`, `unidades`, `min_gems`, `min_coins`, `media7_*` e `un7_*` (a média de 7 dias calculada pelo jogo). Fica de minuto em minuto por 3 dias e depois 1 a cada 15 min (`coletor.podar_vitrine`). |
| `itens` | importer | id → nome (e `icone`), vindos do `items.json` mais os `ITENS_ESPECIAIS` (fragmentos, casas, bicicletas, tickets). |
| `coleta` | importer | Chave/valor da agenda (ver abaixo). |
| `pk_anuncios` | lojapk | Cada anúncio da loja de Pokémon com a ficha completa: `species_id`, nível, shiny, nota, poder, IVs, stats, qualidade, potência, `tipos` (JSON), preço, moeda, vendedor, `ativo`, `primeiro_ms`, `visto_ms` e `sumiu_ms`. Um anúncio que some de uma varredura completa fica com `ativo = 0`. |
| `pk_varreduras` | lojapk | Uma linha por varredura: `snap_ms`, total de anúncios e se foi completa. |
| `alertas_regras` | sinais | Regras de alerta: `tipo` (oportunidade, abaixo, acima, variacao), `item` (NULL para qualquer item), `moeda`, `valor`, `ativo`. |
| `alertas_log` | sinais | Alertas disparados: `regra_id`, `item`, `moeda`, `valor`, `msg`, `ms`, `canais`. |
| `pvp_cache` | pvp | Respostas do Tracker: `chave` (rota + parâmetros), `ms` e `json`. |

**Chaves da tabela `coleta`** (todas em ms, gravadas por `coletor.put` e lidas por `coletor.get`):

| Chave | Quem grava | Significado |
|---|---|---|
| `export_liberado_em` | receber_vendas / receber_recusa | Quando o próximo export pode ser pedido (`esperaMs`/`restaMs` do jogo + 30 s) |
| `export_trava_ate` | rodar (em erro) / decidir_vez | Não pede export antes disso (um pedido sem resposta não trava para sempre) |
| `ultimo_export_em` | receber_vendas | Último export aceito |
| `vitrine_em` | receber_vitrine | Último retrato da vitrine |
| `vitrine_trava_ate` | decidir_vez (legado) | Trava do userscript |
| `vitrine_poda_em` | robo.tarefas_locais | Última poda da vitrine |
| `itens_em` | receber_itens | Último `items.json` baixado |
| `pokemon_em` / `pokemon_tentativa_em` | varrer_loja_pokemon | Última varredura completa e última tentativa (uma tentativa que falha espera 30 min) |
| `pvp_meta_em` | robo.tarefas_locais | Última pré-carga do PvP |
| `catalogo_jogo_em` | robo.tarefas_locais | Último catálogo de espécies do jogo baixado (para o XP/h) |

---

## 6. Comunicação externa

### 6.1 Socket do jogo (`wss://pokeidle.io`, JSON)
O robô usa só isto; o cliente do jogo tem muito mais.

| Envia | Recebe | Uso |
|---|---|---|
| `{"t":"hello","nick","token","delta":1,"dispositivo"}` | `welcome` (e `vivo` enquanto está na fila) | Login. O `dispositivo` é um UUID guardado no config |
| `{"t":"ping"}` a cada 25 s | — | Manter a sessão |
| `{"t":"csv.pedir","tipo":"mercado","filtros":{}}` | `csv` com `ok` + `mercado.linhas` + `esperaMs`, ou `recusa` {`chave`,`restaMs`} | Export de vendas, no máximo 1 por hora |
| `{"t":"market.itens"}` | `market` com `aba:"itens"`, `resumo` {item_id: {anuncios, unidades, minGold, minOrb}} e `medias` | Vitrine |
| `{"t":"market.listar", ...lojapk.FILTRO_TUDO, "moeda", "ordem", "pagina", "especieId":0}` | `market` com `aba:"vitrine"`, `linhas`, `total`, `pagina` e `porPagina` | Loja de Pokémon: 24 por página, teto na página 200, por isso as passadas do mais barato e do mais caro |
| — | `erro` {`chave`} | `RECUSAS_FATAIS` param o robô; `RECUSAS_ESPERAR` (rede cheia) tenta depois |
| — | `sessao.renovada` {`token`} | O token novo é salvo no config |
| — | fechamento com código **4001** | A conta foi aberta em outro lugar |

As moedas do jogo se chamam `orb` (gemas) e `gold` (coins).

### 6.2 Tracker público (`https://pokeidle.io/tracker/api/<rota>`, GET, JSON, sem login)
É o site do botão "Tracker" do PvP. O jogo avisa quando alguém pede rápido demais, então
`pvp.tracker()` espera 1,5 s entre pedidos e guarda cada resposta em `pvp_cache`.

| Rota | Parâmetros | O que traz | Cache |
|---|---|---|---|
| `jogador` | `nick` | `jogador`, `rank` (pontos, tierId, posição, V/D), `totais`, `pokemons` (por espécie), `counters` (para quem perde), `vitimas`, `golpes` e `partidas` (as 20 últimas, com `eu`/`ele` e `pks` dos dois times) | 5 min (o seu) / 6 h (os do topo) |
| `partidas` | `nick`, `temporada` | Mais partidas | — |
| `meta` | `ordem` (uso…), `limite`, `faixa` | Por espécie: `partidas`, `vitorias`, `winrate`, dano por entrada, sobrevivência, `tipos` | 6 h |
| `pokemon` | `id`, `faixa` | A espécie, os `counters` (de quem ela mais perde; o `winrate` da linha é o DELA), as `vitimas` e quem mais usa | 12 h |
| `ladder` | `pagina`, `limite`, `temporada` | Ranking com nick, pontos, V/D e tier | 6 h |
| `inicio`, `golpes`, `guilds`, `busca` | — | Não usadas hoje | — |

Valores de `faixa`: `todas` (sem parâmetro), `baixo`, `alto`, `bronze`, `prata`, `ouro`, `platina`, `diamante`, `mestre`.
Os ids de espécie do Tracker são os mesmos de `pk_anuncios.species_id` (Mega Sceptile = 3254 nos dois).

### 6.3 Outros
- **`https://pokeidle.io/assets/items.json`:** os nomes e ícones dos itens.
- **Ícones na página:** carregados direto de `pokeidle.io` pelo navegador. Nenhuma imagem do jogo fica no repositório.

---

## 7. API do painel (`painel.py`)

Todas as rotas GET aceitam `moeda=gems|coins` (o padrão é gems).

| Rota | Função | O que devolve |
|---|---|---|
| `GET /api/resumo` | `api_resumo` | Lista do mercado: mediana atual, variação de 24 h e 7 d, vendas de 24 h, menor anúncio e mini gráfico de 7 dias |
| `GET /api/item?nome=&janela=24h\|7d\|30d\|tudo` | `api_item` | Detalhe: estatísticas, série do gráfico (baldes), menor anúncio no tempo, vitrine e últimas vendas |
| `GET /api/montagem` | `api_montagem` | Fragmentos × casa/bicicleta pronta (valor esperado por raridade) |
| `GET /api/venda?nome=&qtd=` | `api_venda` → `venda.analisar` | Botão vender: moeda, preços, momento e montagem |
| `GET /api/sinais` | `api_sinais` → `sinais.calcular` | Revenda, barato/caro, regras, log de alertas e canais |
| `GET /api/alertas/novos?desde=ms` | `api_alertas_novos` | Alertas gravados depois de `desde` (para o som) |
| `GET /api/pokemon?busca=&shiny=&limite=` | `api_pokemon` | Vendas recentes de Pokémon |
| `GET /api/pk/buscar?orcamento=&objetivo=&especie=&tipo=&pmin=&nivel=&nota=&shiny=&treinador=&pvp_nick=&pvp_faixa=&transferir=` | `pokemon.buscar` (+ `pvp.pesos_especies` se `objetivo` é `pvp` ou `ponte`; + `venda.cambio` se `ponte`) | Anúncios da loja ordenados pelo objetivo, com o XP/h de cada um (`xp_h`, `xp_hunt`) para o nível de treinador `treinador`. Com `objetivo=ponte`, traz `ponte` (piso, teto e, com `transferir` em gemas, a comissão, quanto recebe e o custo total) e `aviso_pvp` se o Tracker falhou |
| `GET /api/pk/padroes?dias=` | `pokemon.padroes` | Padrões do mercado de Pokémon |
| `GET /api/pvp?nick=&faixa=&orcamento=&moeda=` | `pvp.analisar` | Aba PvP inteira |
| `GET /api/status` | `api_status` → `coletor.status` | Estado da coleta e as últimas linhas do log |
| `POST /api/regras` | `post_regra` | Cria uma regra {tipo, item, moeda, valor} |
| `POST /api/regras/apagar`, `/api/regras/alternar` | `post_regra_acao` | {id} |
| `POST /api/alertas/testar` | `post_testar` | Manda uma notificação de teste |

---

## 8. Módulos, um por um

### `caminhos.py`
Constantes de caminho: `SRC`, `RAIZ`, `CONFIG`, `DADOS`, `BANCO`, `LOG_ROBO`, `AGORA_ROBO`, `WEB`,
`LEGADO` e `USERSCRIPT`. **Toda pasta ou arquivo novo do projeto entra aqui.**

### `notificar.py`
- `config()` lê o bloco `"alertas"` do `config.local.json`.
- `canais_ativos()` lista os canais configurados: `windows` (o padrão no Windows), `discord` e `telegram`.
- `enviar(titulo, texto)` devolve `(canais_ok, erros)`.
  - **Windows:** notificação por PowerShell (`_windows`).
  - **Discord:** webhook.
  - **Telegram:** Bot API.

### `coleta/importer.py`
- **Fuso:** `BRT` fixo em UTC−3, a hora do CSV do jogo.
- **Esquema:** a string `SCHEMA`, com trades, imports, vitrine, itens e coleta.
- **`connect(db_path)`** é o único jeito de abrir o banco. Ele cria as tabelas, migra as colunas novas e grava os `ITENS_ESPECIAIS`.
- **`parse_row`** lê uma linha do CSV.
- **`parse_json_row`** lê uma linha do export JSON, que é o que o robô recebe. A posição 8 traz os atributos do Pokémon.
- **`import_rows(con, rows, fonte)`** faz a deduplicação. O CSV não tem id e vai só até o minuto, então:
  - os minutos completos do arquivo substituem os do banco;
  - no minuto mais antigo, que pode estar cortado, fica a maior contagem de cada linha idêntica.
- **Linha de comando:** `python src/coleta/importer.py [arquivo.csv]` importa os CSVs de `data/inbox/` para `data/processed/`.

### `coleta/coletor.py`
- **Agenda:** `get`/`put` na tabela `coleta`; `agora_ms()`.
- **`receber_vendas` / `receber_recusa` / `receber_falha`** tratam o resultado do export e marcam o próximo horário (`ESPERA_PADRAO_MS` = 1 h, `MARGEM_MS` = 30 s).
- **`receber_vitrine`** grava um retrato. O log ganha uma linha só a cada 15 min (`VITRINE_RESUMO_MS`).
- **`podar_vitrine`** cuida do histórico: depois de `VITRINE_DETALHE_MS` (3 dias), sobra o primeiro retrato de cada faixa de 15 min.
- **`receber_itens`** grava os nomes dos itens.
- **`status`** monta o que a rota `/api/status` mostra.
- **Constantes:** `VITRINE_A_CADA_MS` (1 min) e `ITENS_A_CADA_MS` (1 dia).
- **Legado:** `decidir_vez`, `Handler` e `main()` formam o servidor HTTP do userscript, na porta 8765.

### `coleta/lojapk.py`
- **Constantes:**
  - `INTERVALO_MS`: 3 h entre varreduras;
  - `PAUSA_ENTRE_PAGINAS_S`: 1 s;
  - `ULTIMA_PAGINA`: 200;
  - `PASSADAS`: gemas e coins, do mais barato e do mais caro;
  - `FILTRO_TUDO`: o filtro neutro de `market.listar`;
  - `MOEDA`: orb vira gems e gold vira coins.
- **`preparar(con)`** cria as tabelas.
- **`gravar(con, linhas, t0)`** faz upsert dos anúncios.
- **`finalizar(con, t0, n, completa)`** registra a varredura. Se ela foi completa, marca como inativo o que não foi visto.

### `analise/sinais.py` (Fase 3)
- **`calcular(con, moeda)`** devolve, por item:
  - as medianas de 24 h e 7 d, sem outliers (fora de mediana ×/÷ 4);
  - vendas por dia e liquidez (alta ≥ 20, média ≥ 5);
  - a referência de revenda: a menor entre as medianas de 24 h e 7 d, e só com 10 ou mais vendas em 7 dias;
  - o líquido depois da taxa de 15% (em gemas a taxa é arredondada para cima), o lucro e a margem;
  - o desvio de 24 h contra 7 d e a variação de 7 dias.

  Um anúncio abaixo de referência ÷ 4 fica com `anuncio_fora = True` e não conta como revenda.
- **`TIPOS_REGRA`** tem quatro tipos: oportunidade (margem ≥ X%), abaixo (menor anúncio ≤ X), acima (mediana de 24 h ≥ X) e variacao (variação de 7 d ≥ X%).
- **`avaliar(con)`** confere as regras ativas.
  - O mesmo alerta não se repete por 6 h (`ESPERA_REPETIR_MS`), a menos que melhore 5%.
  - **`registrar`** grava em `alertas_log`.
  - O robô manda no máximo 5 alertas separados; o resto vai junto numa mensagem só.

### `analise/venda.py` (botão vender)
- **`analisar(con, nome, qtd, montagens, raridades)`** é a entrada.
  - **Moeda:** `cambio()` é a mediana ponderada da razão coins/gemas dos itens vendidos nas duas moedas em 48 h. O valor em coins vira gemas descontando mais 15%, a taxa da troca. Coins só ganha se render pelo menos `PREFERENCIA_GEMAS` (5%) a mais. Se o item quase não vende em gemas e vende bem em coins, a indicação é coins.
  - **Preço** (`analisar_moeda`):
    - *rápido:* o menor anúncio menos um passo, mas não abaixo do p10 das vendas;
    - *normal:* a mediana de 12 h;
    - *paciente:* o p75 de 48 h.

    Num mercado fino (menos de 5 vendas em 48 h), o normal vem da média de 7 dias do jogo. O preço rápido some quando ficar em 1º da fila seria dar o item (`anuncio_muito_baixo`).
  - **Momento** (`tendencia` + `_quando`):
    - a tendência é uma reta de Theil-Sen no log das medianas por hora, e a oscilação normal (sigma) sai dos resíduos dessa reta;
    - a tendência é comparada com a inclinação da média de 7 dias do jogo (`_tendencia_jogo`);
    - as saídas são `agora`, `esperar`, `segurar`, `misto`, `tanto_faz` e `sem_dados`;
    - `segurar` tem horizonte de no máximo `SEGURAR_MAX_DIAS` (3).
  - **Confiança e horário:** `_confianca` fica baixa com menos de 3 dias de coleta. `_melhor_hora` só aparece com 3 dias ou mais.
  - **Montagem:** `_montagem` compara vender 10 fragmentos com o valor esperado de montar.

### `analise/pokemon.py` (Fase 4)
- **`Comparaveis`** dá o preço justo de um Pokémon.
  - Com 5 ou mais vendas parecidas (mesma espécie, shiny, moeda, faixa de nível e de nota), usa a mediana delas.
  - Senão, usa o modelo de multiplicadores em log: base da espécie × nível × nota × potência, ajustado por backfitting.
  - Uma espécie cujas vendas saem todas como fora da curva no 2º ajuste fica sem preço base: `preco_justo` confere `(especie, shiny) in base` antes de usar o modelo.
- **`taxa_venda`** calcula a comissão progressiva do jogo para Pokémon.
- **`lado_fisico(species_id, nivel, stats)`** diz quanto da força da espécie é física (0 a 1): os golpes do catálogo liberados no nível, cada um pesando poder ÷ recarga. Sem catálogo, o maior entre ATK e SP.ATK do Pokémon. Guarda em cache por (motor, espécie, nível).
- **`indice_caca(nivel, stats, ivs, fisico)`** é o dano na caça, pela fórmula de dano do jogo: `(2·nível/5 + 2) × (ATK·fisico + SP.ATK·(1−fisico)) × cadência / 100`. A cadência vem do IV de SPD (1 no IV 16, ~0,9 no 1, ~1,14 no 32). Ficam de fora o poder do golpe, a DEF do alvo e o STAB, que valem igual para todos. Os stats do anúncio já vêm no nível dele.
- **`nota_ivs(ivs, fisico)`** é a nota de 0 a 10 dos IVs individuais (`PESO_IV`): 40% o IV do ataque da espécie, 30% o de SPD, 10% cada HP, DEF e SP.DEF. Um IV de ataque ou SPD abaixo de `IV_RUIM` (11) tira até `CASTIGO_IV` (40%). Devolve nota, lado, os dois IVs-chave e os horríveis (`ruins`); a busca manda isso em `ivs_nota`.
- **`comparaveis(con)`** guarda o modelo de preço justo em memória e só o refaz quando entra venda nova (`MAX(rowid)` de `trades`) ou a hora vira. Ajustar do zero leva ~3 s; o painel o prepara ao ligar (`painel.aquecer`).
- **`buscar(...)`** procura na loja (`pk_anuncios`) os anúncios ativos dentro do orçamento e ordena pelo objetivo (`OBJETIVOS`):
  - `xp` ordena pelo XP/h (`caca.xp_do_anuncio`) na melhor hunt liberada para `nivel_treinador`. Funil: só os `FUNIL_XP` (200) melhores pelo índice de caça passam pela conta. Medido na loja inteira, o top 20 em XP/h sempre esteve entre os 100 que mais batem;
  - nos outros objetivos o XP/h é calculado só para os itens que aparecem na lista;
  - `caca` ordena pelo índice de caça; `custo`, pelo índice de caça por gema ou coin;
  - `equilibrado` pesa 60% o percentil do índice de caça e 40% o do desconto (só com confiança alta ou média);
  - `forte` ordena pelo ⚔ (`poder`) do jogo; `barganha`, pelo desconto; `nota`, pela nota;
  - `pvp` usa `pesos_pvp` por `species_id` (`PESO_PVP_ESPECIE`, 60%), o percentil do ⚔ (`PESO_PVP_PODER`, 15%) e o da nota dos IVs (`PESO_PVP_IVS`, 25%).
  - `ponte` (levar gemas de uma conta para a outra): só entram os anúncios até `FOLGA_PONTE` (15%) acima do piso, que é a mediana dos `PISO_K` (10) anúncios ativos mais baratos com os mesmos filtros (um anúncio isolado muito barato não vira o piso; os abaixo do piso também entram); se houver poucos, o teto sobe até o `MIN_PONTE`-ésimo (30) mais barato, sem passar de `TETO_PONTE` (1,5) × o piso. O orçamento, se vier, é teto. Ordena como o `pvp`, com o índice de caça e o preço de desempate. `_conta_ponte` faz a conta da transferência: comissão (`taxa_venda` em gemas), quanto a conta que anunciou recebe e o custo total em gemas com o 1º da lista (comissão + Pokémon pelo câmbio + `DIARIA_ANUNCIO_COINS`). No painel, se o Tracker falhar, a ponte segue só pelo ⚔ e devolve `aviso_pvp`.
- **Por que não o ⚔ para caçar:** no jogo (`shared/nota-pokemon.mjs`), `poder = nível × 10 × score`, e o score é a soma dos seis stats de nascimento numa escala de log entre o pior e o melhor nascimento possíveis. HP, DEF e SP.DEF pesam tanto quanto o ataque, e o log achata as diferenças: o dobro de ATK dá ~30% a mais de ⚔. Dividir o ⚔ pelo preço favorecia os baratos fracos.
- **`padroes(...)`** mostra volume, prêmios por atributo, espécies, horários e compradores.

### `analise/caca.py` (XP por hora de caça)
- **O que responde:** quanto XP/h um Pokémon faz hoje, na melhor hunt liberada para um nível de treinador, sem AoE, TM, bike, casa ou bônus. A explicação completa está no topo do arquivo.
- **Dados** (em `data/jogo/`, fora do git):
  - `catalogo.json`, montado por `baixar_catalogo()` como o cliente do jogo monta. Junta os quatro `assets/creatures*.json` e as correções (`creatures-audit-overrides.json`). Troca os golpes pelos das planilhas de balanceamento (`shared/golpes-planilhas.mjs`, lido por expressão regular em `ler_planilhas`). Injeta os golpes de assinatura de poder 600 (`injetar_golpes_600`) e acrescenta as megas com moveset próprio;
  - `welcome-dados.json`, gravado pelo robô a cada login (`guardar_welcome`): as 1.043 hunts (nível e espécies com peso) e as constantes de caça.
- **`Motor`** carrega os dois uma vez (`motor()` recarrega quando os arquivos mudam e limpa o cache). `Motor.xp_h(species_id, nivel, stats, ivs, tipos, nivel_treinador)` devolve a melhor hunt com XP/h, abates/h, segundos de luta por abate e se morre às vezes.
- **Como fica rápido (~5 ms por Pokémon, contra segundos numa simulação completa):**
  1. só o nível de agora, sem a trilha nível a nível;
  2. uma estimativa fechada (`_estimar`) em todas as hunts liberadas, da mais alta para a mais baixa, com corte pelo teto de XP/h de cada hunt;
  3. a mini-luta (`_hunt`, 16 rolagens de HP, golpe a golpe, saltando os trechos só de Investida) só nas `CANDIDATAS` (8) melhores estimativas.
- **Medido:** contra a busca que simula todas as hunts, mesma hunt e mesmo número em 300 de 300 casos. Contra a calculadora da comunidade, a mesma hunt em 6 de 6 casos, com XP/h entre −15% e +17%.
- **`xp_do_anuncio(m, id, ...)`** é o atalho da busca: lê os JSON de `pk_anuncios` e guarda o resultado por (anúncio, nível do treinador).

### `analise/pvp.py` (aba PvP)
- **Tipos:** `TABELA` é a tabela de tipos da série, a mesma de `shared/tipo-efetividade.mjs` do jogo. `mult(atq, defesa)` dá o multiplicador e `melhor_ataque(atacante, defensor)` o melhor golpe de mesmo tipo.
- **`tracker(con, rota, ttl_s, **params)`:** GET com cache, 1,5 s entre pedidos e a cópia velha guardada se o site falhar. Os erros viram `ErroPvP` com mensagem em português.
- **`atualizar_meta(con)`:** a pré-carga do robô (meta das faixas todas, alto e mestre, mais o ladder e os 10 primeiros perfis).
- **`analisar(con, nick, faixa, orcamento, moeda)`:**
  - `_time_atual`: as espécies das últimas 5 partidas;
  - `_ameacas`: os counters da temporada mais os pokémons nos times das derrotas recentes, com peso nas recentes e no dano;
  - `_buracos` e os tipos que castigam;
  - candidatos por três sinais:
    - 45%: quem ganha das ameaças, pelas páginas `pokemon` delas, com pelo menos `MIN_CONFRONTOS` (20) e confiança n/(n+60);
    - 35%: a taxa no meta do rank, encolhida para 50% (`_nota_meta`);
    - 20%: o encaixe de tipos.
  - com orçamento, `_anuncios` acha na loja o melhor (40% percentil do ⚔ e 60% o da `pokemon.nota_ivs`, dentro da espécie) e o mais barato de cada sugestão;
  - `_resumo_meta` traz os mais usados, a melhor taxa e os times do topo.
- **`pesos_especies(con, faixa, nick)`:** uma nota de 0 a 1 por espécie, para o objetivo `pvp` da busca.

---

## 9. A página (`src/web/`)

- **`index.html`:** o cabeçalho tem as abas (Mercado, Sinais, Montagem, Pokémon), o seletor de moeda, o botão de som e o status.
  - Cada aba é uma `<section id="aba-…" class="aba-corpo">`.
  - Na aba Pokémon, as sub-abas são `data-pksub` (buscar, pvp, padroes, vendas) e os painéis são `id="pk-…"`.
  - A janela do botão vender é `#venda-fundo`.
- **`app.js`:** um arquivo só, dividido em seções por comentários `// ------ nome`.
  - **ícones:** `IMG`, `CATEGORIAS`, `img()`;
  - **formatação:** `fmtNum`, `htmlPreco`, `htmlVar`, `usd`, `classeRaridade` e `api()`, o fetch que lança erro com a mensagem do servidor;
  - **estado na URL:** `lerHash` e `gravarHash`. Aba, moeda, janela, categoria e item ficam no `#`;
  - **lista e detalhe:** `carregarResumo`, `desenharLista` (cada linha tem um botão `[data-vender]`), `selecionar`, `desenharDetalhe`, `ligarCalculadora`;
  - **gráfico:** `desenharGraficos`, em SVG próprio, com mira e tooltip;
  - **montagem:** `carregarMontagem`;
  - **vender:** `abrirVenda`, `desenharVenda`, `ligarVenda` e o estado em `venda`;
  - **sinais:** `carregarSinais`, `desenharSinais`, `ligarSinais`; `postar()` para os POST;
  - **aviso sonoro:** `checarAlertasNovos` (polling), `tocar` (WebAudio), `mostrarAviso`;
  - **PvP:** `analisarPvp`, `desenharPvp`, `ligarPvp`. O nick fica no `localStorage` (`pvp_nick`);
  - **pokémon:** `mostrarSubPk`, `buscarPk`, `carregarPadroesPk`, `carregarPokemon`, `ligarPokemon`;
  - **status e navegação:** `carregarStatus`, `mostrarAba`, `ligar()` (liga todos os eventos) e `iniciar()` (carga inicial e os timers de 1 e 5 min).
- **Regras da página:**
  - todo texto que vem do servidor passa por `esc()` antes de entrar no HTML;
  - os eventos usam delegação no contêiner (por exemplo, `#lista`, `#venda-corpo`), porque o conteúdo é redesenhado;
  - o `localStorage` só guarda conveniências e fica sempre dentro de `try/catch`.
- **`app.css`:** copia o visual do jogo (as cores saíram do CSS público do pokeidle.io).
  - **Fontes, só do sistema:** texto corrido em `--f-texto` (Segoe UI); títulos, botões, abas, rótulos e números em `--f-titulo` (Tahoma negrito). Os títulos levam contorno de 4 pontos (`--contorno-*`), como no jogo. Nenhuma fonte é baixada.
  - **Tokens em `:root`:** `--xadrez-*` (fundo azul), `--mad-*` (madeira), `--rx-*` (roxo), `--vao*` (áreas escuras), `--tinta*`, `--gema`, `--ouro`, `--sobe`, `--desce` e as raridades (`--r-*`). O `app.js` usa `--linha` (fundo dos quadrinhos e do gráfico), `--grade`, `--serie-1`/`--serie-2` e `--tinta*`. As séries foram validadas contra o `--linha`; se mudar um, valide o outro.
  - **Três peças:** o quadro de madeira (`.janela`, `.topo`), o vão (`.janela-corpo`, `.campo`) e o botão. O botão é de madeira quando apagado e roxo quando ligado (`.ativa`) ou de ação (`.btn-primario`). As abas do topo são o botão grande (moldura de 8 px).
  - **Molduras com `box-shadow: inset` empilhados:** a primeira sombra fica por cima. O padding de um botão nunca pode ser menor que a moldura (5 px nos pequenos, 8 px nas abas).
  - **Outros componentes:** `.caixa`, `.tile`/`.tiles`, `.grafico-box`, `.tabela`, `.tag`, `.tipo-tag`, `.var.sobe`/`.var.desce` e o interruptor que substitui todo `input[type=checkbox]`.
  - **Raridade:** as classes `.r-*` só definem `--rar`. A `.linha-item` desenha a faixa da esquerda com ela, e a `.rar-tag` é a versão em linha (na tabela de montagem).
  - As seções novas vão no fim do arquivo, com um comentário `/* ---------- nome ---------- */`.

---

## 10. Configuração (`config.local.json`, fora do git)

```json
{
  "nick": "conta coletora",
  "token": "token da sessão (copiado do console do navegador; ver PLANO.md, Fase 2)",
  "dispositivo": "uuid gerado na primeira vez",
  "alertas": {
    "windows": true,
    "discord_webhook": "https://discord.com/api/webhooks/...",
    "telegram_token": "123:ABC...", "telegram_chat_id": "123456"
  }
}
```

**O token é uma credencial.** Ele nunca pode ser impresso em log, enviado para fora ou commitado. O
robô atualiza o token sozinho quando o jogo manda `sessao.renovada`.

---

## 11. Tempos e limites

| O quê | Valor | Onde |
|---|---|---|
| Export de vendas | o que o jogo mandar (`esperaMs`), ~1 h + 30 s | coletor |
| Vitrine | a cada 1 min | `coletor.VITRINE_A_CADA_MS` |
| Poda da vitrine | a cada 1 h; detalhe por 3 dias, depois 1 a cada 15 min | robo / coletor |
| Loja de Pokémon | a cada 3 h, 1 s entre páginas, tentativa que falha espera 30 min | lojapk / robo |
| Nomes de itens | 1 vez por dia | `coletor.ITENS_A_CADA_MS` |
| Pré-carga do PvP | a cada 6 h | `robo.PVP_META_A_CADA_MS` |
| Catálogo de espécies do jogo (XP/h) | 1 vez por dia, 1 s entre arquivos; falhou, tenta em 1 h | `robo.CATALOGO_A_CADA_MS` |
| Hunts e constantes de caça | a cada login (vêm no `welcome`) | `caca.guardar_welcome` |
| Ping da sessão | 25 s | `Sessao._pingar` |
| Reconexão | 1 min dobrando até 10 min; 4001 espera 30 min; erro 5 min | robo |
| Cache do Tracker | 5 min (você) / 6 h (meta e topo) / 12 h (espécie) | `pvp.TTL_S` |
| Repetição de alerta | 6 h, ou se melhorar 5% | sinais |
| Status no painel | a cada 1 min; dados a cada 5 min; alertas novos a cada 30 s | app.js `iniciar()` / `ligarSom()` |

---

## 12. Regras que não podem ser quebradas

1. **Termos de Uso do jogo:** nada de contornar limites nem sobrecarregar o servidor. Um export por hora, pausas entre páginas, cache no Tracker.
2. **Nada de VPS ou VM:** a equipe do jogo proibiu. Tudo roda no PC do dono.
3. **Uma conexão por conta:** abrir a conta coletora ou as do dono em outro lugar derruba a sessão que já existe (4001). Nunca entre nas contas do dono para testar.
4. **No máximo 4 contas por pessoa,** somando todas as redes. A coletora fica online o tempo todo e conta nesse limite.
5. **O token e o `config.local.json` nunca saem do PC.** O `data/` também não vai para o git.
6. **O repositório é público:** nada de nick de terceiros, dados pessoais ou infraestrutura pessoal nos arquivos versionados.

---

## 13. Como fazer as mudanças mais comuns

**Uma rota nova na API**
1. Escreva a função em `analise/<modulo>.py`. Ela recebe `con` e devolve um dict serializável.
2. Em `painel.py`, `Handler.do_GET`, adicione `if url.path == "/api/x": return self._json(...)`. Limite o tamanho dos parâmetros vindos de `q`.
3. Documente na seção 7 deste arquivo.

**Uma aba ou sub-aba nova na página**
1. Em `index.html`, adicione a sub-aba (`data-pksub="x"` + `<div class="pk-painel hidden" id="pk-x">`) ou uma aba (`data-aba` + `<section id="aba-x" class="aba-corpo hidden">`. Uma aba nova também precisa entrar em `mostrarAba()`).
2. Em `app.js`, crie uma seção `// ------ x` com `carregarX`/`desenharX`/`ligarX` e chame `ligarX()` a partir de `ligar()` ou `ligarPokemon()`.
3. Os estilos vão no fim do `app.css`, usando os tokens.

**Uma tarefa nova no robô**
1. Se ela usa o socket: escreva `async def fazer_x(s: Sessao)` com `s.pedir(...)`. Adicione o horário em `proximos_horarios()` e chame a tarefa em `sessao()`.
2. Se não usa o jogo: escreva dentro de `tarefas_locais()`, com uma chave nova em `coleta`. Se demorar, rode numa thread, como `_precarregar_pvp`.
3. Publique o progresso com `agora(fase=..., detalhe=...)` e, se for uma fase nova, adicione em `mini.FASES`.

**Uma tabela nova:** crie no `SCHEMA` do módulo dono com `CREATE TABLE IF NOT EXISTS` e documente na seção 5.

**Um alerta novo:** adicione o tipo em `sinais.TIPOS_REGRA` e trate em `_checar()`. O formulário da aba Sinais monta o seletor sozinho.

**Religar depois de mudar o código**
- **Pelo menu da bandeja:** Reiniciar robô ou Reiniciar painel.
- **Pelo terminal:** mate o processo `python … src\robo.py` (ou `painel.py`); a bandeja religa em ~30 s.
- **Arquivos de `src/web/`:** não precisam de religação; basta recarregar a página.

---

## 14. Testes e verificação

- **`python testes/teste_robo_sessao.py`:** o robô contra um jogo falso local, numa pasta temporária. Não toca no jogo nem no banco real.
- **Painel de teste:** `.claude/launch.json` sobe uma cópia na porta 8771 (`python src/painel.py --porta 8771`), com o mesmo banco. Dá para testar rotas e página sem derrubar o painel em uso.
- **Experimentos que gravam:** copie `data/market.db` para uma pasta temporária e aponte `importer.connect` para a cópia.
- **Verificação rápida:**
  - `python -m py_compile src/*.py src/coleta/*.py src/analise/*.py`;
  - `node --check src/web/app.js`;
  - `curl` em cada rota de `/api/`.
- **Inicialização com o Windows:** teste abrindo o atalho pelo Explorer (`explorer.exe "<Startup>\PokeIdle Tracker.lnk"`), não por um terminal. Um processo iniciado pelo Explorer pode não enxergar pacotes instalados por um terminal com ambiente diferente.

---

## 14.1 Fórmulas do jogo (Pokémon)

Os módulos `shared/` do jogo são públicos (por exemplo, `https://pokeidle.io/shared/nota-pokemon.mjs`). Os que importam aqui:
- **Stat:** `arred((base + refino + 2×IV) × nível/100 × qualidade^exp × potência × shiny × lendário)`.
  - O expoente da qualidade é 0,95 para HP e SPD e 0,8 para os outros.
  - A potência multiplica por 1; 1,05; 1,1; 1,25; 2 (P1 a P5). Shiny multiplica por 3; lendário e mítico, por 4.
  - IV vai de 1 a 32 por stat (6 a 192 somados). A qualidade vai de 0,8 a 1,8, e metade dos nascimentos fica abaixo de ~1,08.
- **Nota (N=):** de 0 a 10 **dentro da espécie**, no nível 100. O 0 é o pior nascimento possível (IV 6, Q 0,8, P1) e o 10 o melhor (IV 192, Q 1,8, P5, shiny), em escala de log da soma dos stats. Uma evolução sobe a nota em pelo menos 0,1. O ×4 do lendário fica fora da nota.
- **⚔ (poder):** `nível × 10 × score`, com o score em log (ver `analise/pokemon.py`).
- **Mercado:** só aceita Pokémon de nível ≥ 50 e nota ≥ 3,5. Shiny, P5, lendário e mítico passam livres. **Shiny só se anuncia em gemas** (desde 10/10/2026).
- **Dano na caça:** `((2·nível/5 + 2) × poder do golpe × ATK/DEF) / 50 + 2`, × STAB × efetividade. Na caça, a efetividade é ampliada em 1,5: 2× vira 2,5× e 0,5× vira 0,33×. O golpe usa ATK ou SP.ATK conforme a categoria.
- **Golpes:**
  - os das planilhas de balanceamento valem desde o nível 1, com recarga pela curva do poder (10 s no poder 15, 30 s no 100, 60 s no 600);
  - toda última evolução ganha um golpe de 600 de cada tipo seu (dois se tiver um tipo só), no lado de ataque mais forte, com 60 s de recarga;
  - a Investida (poder 30, 2 s) sai quando nenhum golpe está pronto. O intervalo entre golpes é 0,9 s, e a Investida e o intervalo caem 10 ms por ponto de IV de SPD.
- **Selvagem:** stats `(base + 2×16) × nível/100`; vida de combate `máx(24, HP × 12) × 5`; dano dele × 1,8, um golpe a cada 1,4 s.
- **XP do abate:** uma curva só, pelo nível do selvagem: `⌊0,6·n²⌋ + 8` até 150; acima, `13.500 × (n/150)^1,25`.
- **Hunt liberada:** nível do treinador ≥ nível da hunt.

## 15. Armadilhas conhecidas

- **Fim de linha:** `.py` usa LF e `.bat` usa CRLF (`.gitattributes`). No Windows, `Path.write_text` grava CRLF; para `.py`, use `write_bytes` ou `open(..., newline="\n")`.
- **`pythonw` não tem stdout:** os filhos da bandeja têm a saída redirecionada para arquivos. Não use `print` esperando um console.
- **Dois mercados no mesmo item:** pedras são vendidas em lote a 2 gemas por unidade e avulsas a dezenas ou centenas de gemas. Sempre filtre outliers (mediana ×/÷ 4) antes de comparar preços.
- **Coleta curta:** tendências e "melhor horário" ficam pouco confiáveis nos primeiros dias, e a interface mostra a confiança. A média de 7 dias do jogo (`vitrine.media7_*`) ajuda nesse começo.
- **O teto da loja de Pokémon é a página 200:** por isso a varredura faz as passadas do mais barato e do mais caro.
- **O export vem atrasado:** uma venda pode chegar ao banco até ~1 h depois de acontecer. Contagens das últimas horas sobem com o tempo.
- **Idle Deck:** as contas de caça do dono rodam lá (é um app fechado). O projeto não automatiza essas contas; o PvP lê só o Tracker público.
- **Dados do XP/h:** a busca mostra "sem os dados do jogo ainda" até o robô entrar uma vez (hunts) e baixar o catálogo. Se o jogo mudar o formato do `welcome` ou da planilha de golpes, compare com `data/jogo/welcome-esqueleto.json` e com a contagem de `ler_planilhas` (26 tabelas, ~1.100 espécies e ~90 megas em 11/2026).
