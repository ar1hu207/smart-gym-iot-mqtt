// Dashboard Smart Gym: recebe o estado via SSE (/eventos) e redesenha a página.
// Nenhum refresh manual: o servidor empurra um snapshot a cada mensagem MQTT.
(() => {
  "use strict";

  const $ = (seletor) => document.querySelector(seletor);
  const ROTULOS = { livre: "Livre", ocupada: "Ocupada", offline: "Offline" };

  // Payloads vêm de um broker MQTT (às vezes público): sempre escapar antes de inserir no HTML.
  const esc = (valor) =>
    String(valor ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const hora = (iso) => (iso ? new Date(iso).toLocaleTimeString("pt-BR") : "—");

  const num = (valor, casas = 2) => {
    const n = Number(valor);
    return valor === null || valor === undefined || Number.isNaN(n)
      ? "—"
      : n.toLocaleString("pt-BR", { maximumFractionDigits: casas });
  };

  const duracao = (segundos) => {
    const s = Math.max(0, Math.floor(segundos));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const x = s % 60;
    return (h ? `${h}:` : "") + `${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
  };

  const situacao = (e) => {
    if (e.online === false) return "offline";
    if (e.status === "Ocupada") return "ocupada";
    if (e.status === "Livre") return "livre";
    return "offline";
  };

  const situacaoAnterior = {};
  const historicoVisto = new Set();
  let primeiraCarga = true;

  // ── Estações ──────────────────────────────────────────
  function cartaoEstacao(e) {
    const sit = situacao(e);
    const mudou = situacaoAnterior[e.id] !== undefined && situacaoAnterior[e.id] !== sit;
    situacaoAnterior[e.id] = sit;

    let corpo = "";
    if (sit === "ocupada") {
      corpo = `
        <dl class="detalhes">
          <dt>Aluno</dt><dt class="direita">Em uso há</dt>
          <dd>${esc(e.aluno || "—")}</dd><dd class="direita mono" data-desde="${esc(e.desde)}">--:--</dd>
        </dl>`;
    } else if (sit === "livre") {
      corpo = `
        <dl class="detalhes">
          <dt>Disponível desde</dt><dt></dt>
          <dd class="mono">${hora(e.desde)}</dd><dd></dd>
        </dl>`;
    } else {
      corpo = `<p class="vazio">Estação sem conexão com o broker (Last Will recebido).</p>`;
    }

    const s = e.ultima_serie;
    if (s && sit === "ocupada") {
      const fimDescanso = new Date(s.recebido_em).getTime() + s.descanso_sugerido_s * 1000;
      corpo += `
        <div class="ultima">
          <span class="ultima-rotulo">Última série publicada</span>
          <strong>Série ${esc(s.serie)} · ${esc(s.repeticoes)} reps</strong>
          <span class="sub">${num(s.cadencia_media_s)} s por repetição · ${num(s.duracao_s, 0)} s de série</span>
          ${(s.alertas || []).slice(0, 2).map((a) => `<span class="alerta">⚠ ${esc(a)}</span>`).join("")}
          <div class="descanso" data-fim="${fimDescanso}" data-total="${esc(s.descanso_sugerido_s)}">
            <div class="descanso-barra"><span style="width:100%"></span></div>
            <span class="descanso-txt">Descanso sugerido ${esc(s.descanso_sugerido_s)} s</span>
          </div>
        </div>`;
    }

    return `
      <article class="estacao ${sit}${mudou ? " mudou" : ""}" aria-label="${esc(e.nome)}: ${ROTULOS[sit]}">
        <div class="estacao-topo">
          <div><h3>${esc(e.nome)}</h3><span class="sub">${esc(e.exercicio || "")}</span></div>
          <span class="estacao-id">${esc(e.id)}</span>
        </div>
        <div class="farol"><span class="lampada"></span><span class="farol-rotulo">${ROTULOS[sit]}</span></div>
        ${corpo}
      </article>`;
  }

  function renderEstacoes(estacoes) {
    const alvo = $("#estacoes");
    if (!estacoes.length) {
      alvo.innerHTML = `<p class="vazio">Nenhuma estação publicou ainda. Rode <code>python -m station.main</code> ou o simulador.</p>`;
      return;
    }
    alvo.innerHTML = estacoes.map(cartaoEstacao).join("");
  }

  // ── Histórico ─────────────────────────────────────────
  function renderHistorico(series) {
    const alvo = $("#historico");
    if (!series.length) {
      alvo.innerHTML = `<tr><td colspan="8" class="vazio">Nenhuma série registrada ainda.</td></tr>`;
      return;
    }
    alvo.innerHTML = series
      .map((s) => {
        const nova = !primeiraCarga && !historicoVisto.has(s.id);
        historicoVisto.add(s.id);
        const obs = [
          s.fadiga ? `<span class="badge badge-fadiga">fadiga</span>` : `<span class="badge badge-ok">ok</span>`,
          esc((s.alertas || []).join(" · ")),
        ].join("");
        return `
          <tr class="${nova ? "nova" : ""}">
            <td class="mono">${hora(s.ts)}</td>
            <td>${esc(s.aluno)}</td>
            <td>${esc(s.estacao_nome || s.estacao_id)}</td>
            <td class="num">${esc(s.serie)}</td>
            <td class="num"><span class="reps-total">${esc(s.repeticoes)}</span>${
              s.repeticoes_incompletas
                ? `<span class="reps-parcial" title="repetições com amplitude incompleta">+${esc(s.repeticoes_incompletas)}</span>`
                : ""
            }</td>
            <td class="num">${num(s.cadencia_media_s)} s</td>
            <td class="num">${esc(s.descanso_sugerido_s)} s</td>
            <td class="obs">${obs}</td>
          </tr>`;
      })
      .join("");
  }

  // ── Acessos RFID ──────────────────────────────────────
  const ICONES = { LIBERADO: "✓", NEGADO: "✕", SAIDA: "↩" };
  const VERBOS = { LIBERADO: "entrou em", NEGADO: "barrado em", SAIDA: "saiu de" };

  function renderAcessos(acessos) {
    const alvo = $("#acessos");
    if (!acessos.length) {
      alvo.innerHTML = `<li class="vazio">Nenhuma leitura de cartão ainda.</li>`;
      return;
    }
    alvo.innerHTML = acessos
      .map(
        (a) => `
        <li class="${esc(a.resultado)}">
          <span class="icone">${ICONES[a.resultado] || "•"}</span>
          <span><strong>${esc(a.aluno || `Cartão ${a.uid}`)}</strong> ${VERBOS[a.resultado] || ""} ${esc(a.estacao_nome || a.estacao_id)}
            <span class="motivo">${esc(a.motivo)}</span></span>
          <time class="mono">${hora(a.ts)}</time>
        </li>`
      )
      .join("");
  }

  // ── Resumo e conexões ─────────────────────────────────
  function renderResumo(resumo, broker) {
    $("#kpi-livres").textContent = resumo.livres;
    $("#kpi-ocupadas").textContent = resumo.ocupadas;
    $("#kpi-series").textContent = resumo.series;
    $("#kpi-reps").textContent = resumo.repeticoes;
    $("#topico").textContent = `${broker.topico_raiz}/+/{status, performance, acesso, conexao}`;

    const pill = $("#pill-broker");
    pill.className = `pill ${broker.conectado ? "pill-ok" : "pill-erro"}`;
    pill.querySelector("span").textContent = `MQTT ${broker.endereco}`;
  }

  // ── Relógios (sem depender de novas mensagens) ────────
  function atualizarTempos() {
    const agora = Date.now();
    $("#relogio").textContent = new Date(agora).toLocaleTimeString("pt-BR");

    document.querySelectorAll("[data-desde]").forEach((el) => {
      const inicio = Date.parse(el.dataset.desde);
      if (!Number.isNaN(inicio)) el.textContent = duracao((agora - inicio) / 1000);
    });

    document.querySelectorAll(".descanso").forEach((el) => {
      const restante = (Number(el.dataset.fim) - agora) / 1000;
      const total = Number(el.dataset.total) || 1;
      const barra = el.querySelector(".descanso-barra span");
      const texto = el.querySelector(".descanso-txt");
      if (restante > 0) {
        el.classList.remove("pronto");
        barra.style.width = `${Math.min(100, (restante / total) * 100)}%`;
        texto.textContent = `Descanso: ${Math.ceil(restante)} s de ${total} s`;
      } else {
        el.classList.add("pronto");
        barra.style.width = "100%";
        texto.textContent = "Descanso concluído — pronto para a próxima série";
      }
    });
  }

  // ── Notificações ──────────────────────────────────────
  function toast(titulo, texto, tipo = "") {
    const el = document.createElement("div");
    el.className = `toast ${tipo}`;
    el.innerHTML = `<strong>${esc(titulo)}</strong>${esc(texto)}`;
    $("#toasts").prepend(el);
    setTimeout(() => el.remove(), 5000);
    while ($("#toasts").children.length > 4) $("#toasts").lastChild.remove();
  }

  function notificar(tipo, d) {
    if (!d) return;
    if (tipo === "performance") {
      toast(`${d.aluno} concluiu a série ${d.serie}`, `${d.estacao_nome}: ${d.repeticoes} repetições · descanso ${d.descanso_sugerido_s} s`);
    } else if (tipo === "acesso" && d.resultado === "NEGADO") {
      toast(`Acesso negado — ${d.estacao_nome}`, d.motivo + (d.uid ? ` (${d.uid})` : ""), "erro");
    } else if (tipo === "status") {
      toast(`${d.estacao}: ${d.status}`, d.aluno ? `Aluno: ${d.aluno}` : "Máquina liberada", d.status === "Livre" ? "ok" : "erro");
    }
  }

  // ── Stream SSE ────────────────────────────────────────
  function aplicar(mensagem) {
    const estado = mensagem.estado;
    renderResumo(estado.resumo, estado.broker);
    renderEstacoes(estado.estacoes);
    renderHistorico(estado.historico);
    renderAcessos(estado.acessos);
    atualizarTempos();
    if (!primeiraCarga) notificar(mensagem.tipo, mensagem.destaque);
    primeiraCarga = false;
  }

  function conectar() {
    const pill = $("#pill-stream");
    const fonte = new EventSource("/eventos");
    fonte.addEventListener("estado", (ev) => aplicar(JSON.parse(ev.data)));
    fonte.onopen = () => {
      pill.className = "pill pill-ok";
      pill.querySelector("span").textContent = "Ao vivo";
    };
    fonte.onerror = () => {
      // O EventSource reconecta sozinho; só sinalizamos na tela.
      pill.className = "pill pill-aguardando";
      pill.querySelector("span").textContent = "Reconectando…";
    };
  }

  conectar();
  atualizarTempos();
  setInterval(atualizarTempos, 1000);
})();
