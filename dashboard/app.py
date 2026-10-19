"""
Dashboard Web de monitoramento da Smart Gym (Flask + MQTT + SSE).

    Estação --publish--> Broker MQTT --subscribe--> este servidor --SSE--> navegador

Uso (a partir da raiz do repositório):
    python -m dashboard.app          # http://localhost:5000
"""

import json
import os
import queue
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, stream_with_context

from shared import config
from shared.mqtt_cliente import descricao_broker
from dashboard.armazenamento import Armazenamento
from dashboard.assinante import AssinanteMQTT
from dashboard.painel import Painel

PASTA = Path(__file__).resolve().parent
CAMINHO_BANCO = Path(os.getenv("DASHBOARD_BANCO", PASTA / "dados" / "smartgym.db"))
INTERVALO_PING_S = 15


def criar_app(iniciar_mqtt: bool = True) -> Flask:
    app = Flask(__name__)
    painel = Painel(Armazenamento(CAMINHO_BANCO), broker=descricao_broker(), topico_raiz=config.TOPICO_RAIZ)
    app.config["painel"] = painel

    if iniciar_mqtt:
        AssinanteMQTT(painel).iniciar()

    @app.get("/")
    def inicio():
        return render_template("index.html")

    @app.get("/api/estado")
    def estado():
        return jsonify(painel.snapshot())

    @app.get("/eventos")
    def eventos():
        """Stream SSE: envia o estado completo agora e a cada nova mensagem MQTT."""
        fila = painel.inscrever()

        def gerar():
            try:
                inicial = {"tipo": "inicial", "destaque": None, "estado": painel.snapshot()}
                yield f"event: estado\ndata: {json.dumps(inicial, ensure_ascii=False)}\n\n"
                while True:
                    try:
                        mensagem = fila.get(timeout=INTERVALO_PING_S)
                        yield f"event: estado\ndata: {json.dumps(mensagem, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        yield ": ping\n\n"  # mantém a conexão viva atrás de proxies
            finally:
                painel.desinscrever(fila)

        return Response(
            stream_with_context(gerar()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


if __name__ == "__main__":
    porta = int(os.getenv("DASHBOARD_PORTA", "5000"))
    print(f"[Dashboard] http://localhost:{porta}  |  broker {descricao_broker()}  |  tópicos {config.TOPICO_RAIZ}/#")
    criar_app().run(host="0.0.0.0", port=porta, threaded=True, debug=False)
