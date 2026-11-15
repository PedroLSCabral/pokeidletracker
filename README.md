# PokeIdle Tracker

Coleta e análise do mercado do [pokeidle.io](https://pokeidle.io), onde as gemas valem dinheiro de verdade.

Um robô lê o mercado do jogo e grava num banco SQLite local. Ele chega ao jogo pela **extensão do Idle Deck** (a aba de uma das suas contas empresta o socket que o jogo já tem aberto) ou, no jeito antigo, entrando sozinho com uma conta só para coleta. O que ele lê:

- as vendas do mercado (o export de 1 em 1 hora que o próprio jogo oferece);
- a vitrine de itens (menor anúncio e média de 7 dias de cada item), a cada minuto;
- a loja de Pokémon inteira, a cada 3 horas.

Um painel web com o visual do jogo mostra preços, sinais de revenda, alertas e um analisador de Pokémon. O analisador estima o preço justo de cada anúncio e procura o melhor Pokémon para um orçamento. A aba PvP lê o seu histórico no Tracker público do jogo e sugere o que comprar contra quem você mais perde.

O plano completo, as descobertas sobre o jogo e as decisões estão em [docs/PLANO.md](docs/PLANO.md); o mapa técnico do código, em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

> **Projeto pessoal e não oficial,** sem relação com a equipe do pokeidle.io. Os Termos de Uso do jogo permitem automação desde que ela não burle limites nem sobrecarregue o servidor; o robô foi feito para ficar dentro disso (veja "Regras que o robô respeita"). Use por sua conta e risco. A extensão só faz três leituras (export, vitrine e loja de Pokémon) e nunca lê o token da conta.

## Como usar (Windows)

1. **Instale Python 3.12 ou mais novo e as dependências:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Ligue o robô ao jogo,** de um destes jeitos:
   - **Extensão do Idle Deck (recomendado):** na janela de Extensões de uma conta, ligue o *Modo desenvolvedor*, clique em *Carregar pasta…* e escolha a pasta `extensao/` deste projeto. Um pontinho no canto de baixo da aba fica verde quando o robô está ligado. Depois de atualizar o projeto, use *Recarregar da pasta*.
   - **Conta só para coleta:** `python src/robo.py --configurar` pede o nick e o token, copiados do console do navegador (passo a passo no [docs/PLANO.md](docs/PLANO.md), Fase 2). Eles ficam em `config.local.json`, que **nunca** vai para o git. Quando uma aba da extensão liga, o robô larga essa conta e passa a usar só a extensão.
3. **Ligue tudo com dois cliques em `iniciar.bat`.** O robô e o painel rodam escondidos, e aparece uma pokébola na bandeja, perto do relógio:
   - o duplo clique abre o painel;
   - um clique abre uma janelinha de status (o que o robô está fazendo e quando é a próxima tarefa);
   - o botão direito abre o menu, no visual do jogo (estado, painel, log, reiniciar, ligar com o Windows, sair).
4. **Abra o painel em http://127.0.0.1:8770.**

Para ligar junto com o Windows, marque a opção no menu da pokébola ou rode `python src/bandeja.py --instalar`.

> **Rode no seu próprio PC.** A equipe do jogo confirmou que VPS (máquina virtual na nuvem) não é permitido.

## Estrutura

| Pasta / arquivo | O que tem |
|---|---|
| `src/bandeja.py` | Ícone na bandeja: mantém o robô e o painel rodando escondidos e os religa se caírem |
| `src/robo.py` | Robô coletor: fica ligado ao jogo (pela extensão ou por uma conta) e lê a vitrine, o export e a loja de Pokémon |
| `extensao/` | Extensão do Idle Deck: liga a aba de uma conta ao robô do PC, pelo socket do próprio jogo |
| `src/painel.py` | Servidor do painel (API JSON + a página de `src/web/`) |
| `src/mini.py` | Janelinha de status, que abre pelo ícone |
| `src/menu_bandeja.py`, `src/tema.py` | Menu do botão direito e o visual do jogo nas janelas da bandeja |
| `src/coleta/` | O que grava no banco: esquema e importação (`importer`), vendas/vitrine/agenda (`coletor`), loja de Pokémon (`lojapk`) |
| `src/analise/` | O que calcula: revenda e alertas (`sinais`), botão vender (`venda`), Pokémon (`pokemon`), PvP (`pvp`) |
| `src/web/` | A página do painel com o visual do jogo (HTML, CSS e JS sem dependências; ícones carregados do site do jogo) |
| `src/caminhos.py`, `src/notificar.py` | Pastas do projeto; avisos pelo Windows, Discord ou Telegram |
| `testes/` | Robô contra um jogo falso e contra uma aba falsa da extensão, sem tocar no pokeidle.io |
| `legado/` | Primeira tentativa de coleta, por userscript (não funcionou no Idle Deck; a extensão tomou o lugar) |
| `docs/` | [`ARQUITETURA.md`](docs/ARQUITETURA.md) (o mapa técnico) e [`PLANO.md`](docs/PLANO.md) (o diário do projeto) |

Os dados ficam em `data/`, também fora do git: `market.db`, os logs e `robo_agora.json`.

**Vai mexer no código?** Comece pelo [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) e pelo [`CLAUDE.md`](CLAUDE.md).

## Regras que o robô respeita

- **1 export por hora,** pelo tempo que o próprio jogo devolve.
- **Pausa de 1 s entre as páginas da loja.**
- **Uma conexão por conta.** A extensão usa o socket que o jogo já abriu, sem login novo. No modo conta, se ela for aberta em outro lugar, o robô espera em vez de disputar a sessão.
- **Um robô por PC.**
- **Nada de contornar limites do jogo,** conforme os Termos de Uso.
- **Nada de VPS:** roda só no PC, como a equipe do jogo pediu.
