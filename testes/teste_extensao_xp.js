// Teste da extensão "Ritmo de XP" (extensao-xp/) sem tocar no jogo.
//   node testes/teste_extensao_xp.js            → só as contas (calculo.js)
//   node testes/teste_extensao_xp.js --tela     → também a tela, numa aba falsa do jogo (Playwright)
// Na aba falsa, o WebSocket é trocado por um que só entrega mensagens montadas aqui: welcome,
// depois `estado` parciais com XP subindo, com e sem bônus.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const PASTA = path.join(__dirname, '..', 'extensao-xp');
const C = require(path.join(PASTA, 'calculo.js'));
const H = C.HORA;

// --- curva (a do jogo: shared/boost-atrasados.mjs)
assert.strictEqual(C.xpTotal(1), 0);
assert.strictEqual(C.xpTotal(2), 100);
assert.strictEqual(C.xpTotal(100), 15694800);
for (const L of [2, 7, 99, 150, 1000]) {
  assert.strictEqual(C.nivelPeloXp(C.xpTotal(L)), L);
  assert.strictEqual(C.nivelPeloXp(C.xpTotal(L) - 1), L - 1);
}

// --- ritmo: o cru tira o bônus de cada momento
{
  const s = [{ t: 0, xp: 0, mult: 2 }, { t: H / 2, xp: 1000, mult: 2 }, { t: H, xp: 2000, mult: 1 }];
  const r = C.medirRitmo(s, H, H);
  assert.strictEqual(Math.round(r.medidoH), 2000);
  assert.strictEqual(Math.round(r.cruH), 1500);
  const meia = C.medirRitmo(s, H, H / 2);   // só a 2ª metade
  assert.strictEqual(Math.round(meia.medidoH), 2000);
  assert.strictEqual(Math.round(meia.cruH), 2000);
  assert.strictEqual(C.medirRitmo([{ t: 0, xp: 5, mult: 1 }], H, H), null);
}

// --- projeção: bônus que acaba no meio, e o dos Atrasados (por XP e por tempo)
{
  const p = C.projecao({ xp: 0, cruH: 1000, bonus: [{ f: 1.5, ateMs: H }] });
  assert.strictEqual(Math.round(p.tempoAte(1500) / 60000), 60);
  assert.strictEqual(Math.round(p.tempoAte(2500) / 60000), 120);
  assert.strictEqual(Math.round(p.xpEm(2 * H)), 2500);
  assert.strictEqual(p.tempoAte(0), 0);
  const semBonusAcabar = C.projecao({ xp: 0, cruH: 1000, bonus: [{ f: 1.5, ateMs: Infinity }] });
  assert.strictEqual(Math.round(semBonusAcabar.tempoAte(3000) / 60000), 120);

  const porXp = C.projecao({ xp: 0, cruH: 100, atrasados: { f: 10, xpFim: 1000 } });
  assert.strictEqual(Math.round(porXp.tempoAte(1000) / 60000), 60);
  assert.strictEqual(Math.round(porXp.tempoAte(1100) / 60000), 120);
  assert.strictEqual(Math.round(porXp.xpEm(2 * H)), 1100);
  const porTempo = C.projecao({ xp: 0, cruH: 100, bonus: [{ f: 2, ateMs: 3 * H }], atrasados: { f: 10, ateMs: H } });
  assert.strictEqual(Math.round(porTempo.xpEm(H)), 2000);
  assert.strictEqual(Math.round(porTempo.xpEm(4 * H)), 2000 + 400 + 100);
  assert.strictEqual(Math.round(porTempo.tempoAte(2500) / 60000), 240);

  const parado = C.projecao({ xp: 10, cruH: 0 });
  assert.strictEqual(parado.tempoAte(11), Infinity);
}

// --- tabela nível a nível
{
  const p = C.projecao({ xp: C.xpTotal(100), cruH: 1e6 });
  const l = C.linhasAteAlvo(p, C.xpTotal(100), 100, 105);
  assert.deepStrictEqual(l.map((x) => x.nivel), [101, 102, 103, 104, 105]);
  assert.ok(l.every((x, i) => i === 0 || x.ms > l[i - 1].ms));
  const longa = C.linhasAteAlvo(p, C.xpTotal(100), 100, 1000, 40);
  assert.ok(longa.length <= 41 && longa[longa.length - 1].nivel === 1000);
}
assert.strictEqual(C.tempoCurto(90 * 60000), '1 h 30 min');
assert.strictEqual(C.tempoCurto(26 * H), '1 d 2 h');
console.log('contas: ok');

if (!process.argv.includes('--tela')) process.exit(0);

// ------------------------------------------------------------------ a tela, numa aba falsa
(async () => {
  const { chromium } = require('playwright');
  const navegador = await chromium.launch();
  const pagina = await navegador.newPage();
  const erros = [];
  pagina.on('pageerror', (e) => erros.push(String(e)));
  pagina.on('console', (m) => { if (m.type() === 'error') erros.push(m.text()); });
  await pagina.route('https://pokeidle.io/**', (r) => r.fulfill({ contentType: 'text/html', body: '<!doctype html><title>jogo</title><body><h1>jogo falso</h1></body>' }));

  // um WebSocket falso: guarda as instâncias para o teste entregar mensagens
  await pagina.addInitScript(() => {
    class SocketFalso extends EventTarget {
      constructor(url) { super(); this.url = url; this.readyState = 1; (window.__sockets ??= []).push(this); }
      send() { (window.__enviados ??= []).push([...arguments]); }
      close() {}
    }
    window.WebSocket = SocketFalso;
    window.__entregar = (o) => { for (const s of window.__sockets) s.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(o) })); };
    // relógio controlado pelo teste
    const real = Date.now.bind(Date);
    window.__avanco = 0;
    Date.now = () => real() + window.__avanco;
  });
  await pagina.addInitScript({ content: fs.readFileSync(path.join(PASTA, 'calculo.js'), 'utf8') });
  await pagina.addInitScript({ content: fs.readFileSync(path.join(PASTA, 'ritmo.js'), 'utf8') });
  await pagina.goto('https://pokeidle.io/');
  await pagina.evaluate(() => new WebSocket('wss://pokeidle.io/ws'));

  const agora = await pagina.evaluate(() => Date.now());
  const pk = { id: 7, speciesId: 6, nome: 'Charizard', level: 120, xp: C_xp(120), xpNivel: 0, xpProximo: 0 };
  function C_xp(L) { return C.xpTotal(L); }
  const estado = {
    cheio: true, nick: 'teste', level: 200, xp: C.xpTotal(200) + 5000, xpNivel: C.xpTotal(200), xpProximo: C.xpTotal(201),
    servidorAgora: agora, activeId: 7, guildBonusPct: 0, twitch: { pct: 15 }, kick: { pct: 15 },
    loja: { alvoAtrasados: 0, boosts: {} },
    bonusXp: { tr: 1.5 * 1.5, pk: 1.5, partes: [{ id: 'vip', tr: 1.5, pk: 1.5, ate: agora + 100 * H }, { id: 'boostXp', tr: 1.5, pk: 1, ate: agora + 2 * H }] },
    pokemons: [pk],
  };
  await pagina.evaluate((m) => window.__entregar(m), { t: 'welcome', tiposBoost: [{ chave: 'xp', mult: 1.5 }, { chave: 'pokexp', mult: 1.5 }], estado });

  // 30 min caçando: +1.000.000 de XP do treinador (com ×2,25) e +600.000 do Pokémon (com ×1,5)
  for (let i = 1; i <= 30; i++) {
    await pagina.evaluate(([i, xpTr, xpPk]) => {
      window.__avanco = i * 60_000;
      window.__entregar({ t: 'estado', estado: { xp: xpTr, servidorAgora: Date.now(), pkMud: [{ id: 7, speciesId: 6, nome: 'Charizard', level: 120, xp: xpPk }] } });
    }, [i, estado.xp + i * 1e6 / 30, pk.xp + i * 6e5 / 30]);
  }
  await pagina.locator('#pokeidle-ritmo-xp .bt').click();
  await pagina.locator('#pokeidle-ritmo-xp [data-resultado] .grande').waitFor();
  const texto = async () => pagina.locator('#pokeidle-ritmo-xp .pn').innerText();
  let t = await texto();
  console.log(t);
  // medido: 2 mi XP/h com +125% de bônus → cru ~889 mil; com os marcados (VIP e XP Boost) volta a 2 mi
  assert.ok(/Ritmo: 2 mi XP\/h/.test(t), 'ritmo medido');
  assert.ok(/Sem bônus: 888,[89] mil XP\/h/.test(t), 'ritmo sem bônus');
  assert.ok(/VIP/.test(t) && /XP Boost/.test(t) && /Bônus Twitch/.test(t), 'lista de bônus');
  const tempoCom = await pagina.locator('#pokeidle-ritmo-xp .grande').innerText();

  // desliga o VIP: a estimativa tem que ficar mais longa
  await pagina.locator('#pokeidle-ritmo-xp [data-bn="vip"]').uncheck();
  t = await texto();
  const tempoSem = await pagina.locator('#pokeidle-ritmo-xp .grande').innerText();
  assert.notStrictEqual(tempoCom, tempoSem);
  assert.ok(/com os marcados: 1,33 mi/.test(t), 'sem VIP sobra só o XP Boost');

  // alvo digitado e tabela
  await pagina.locator('#pokeidle-ritmo-xp [data-alvo]').fill('205');
  await pagina.locator('#pokeidle-ritmo-xp summary').click();
  t = await texto();
  assert.ok(/Nv 200 → 205/.test(t), 'alvo digitado');
  assert.ok(/\b205\b/.test(await pagina.locator('#pokeidle-ritmo-xp table').innerText()), 'tabela até o alvo');

  // o Pokémon ativo: o XP Boost não vale para ele
  await pagina.locator('#pokeidle-ritmo-xp [data-quem]').selectOption('pk:7');
  t = await texto();
  assert.ok(/Ritmo: 1,2 mi XP\/h/.test(t), 'ritmo do Pokémon');
  assert.ok(!/XP Boost\b(?! Pokémon)/.test(t.replace('XP Boost Pokémon', '')), 'XP Boost do treinador fora da lista do Pokémon');

  // padrão da conta volta o VIP
  await pagina.locator('#pokeidle-ritmo-xp [data-quem]').selectOption('tr');
  await pagina.locator('#pokeidle-ritmo-xp [data-padrao]').click();
  assert.ok(await pagina.locator('#pokeidle-ritmo-xp [data-bn="vip"]').isChecked());
  await pagina.screenshot({ path: process.env.FOTO || path.join(require('os').tmpdir(), 'ritmo-xp.png') });

  assert.ok(!(await pagina.evaluate(() => window.__enviados?.length)), 'a extensão não pode mandar nada pelo socket');
  assert.deepStrictEqual(erros, []);
  await navegador.close();
  console.log('tela: ok');
})().catch((e) => { console.error(e); process.exit(1); });
