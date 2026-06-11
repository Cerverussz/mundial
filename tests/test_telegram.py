import httpx

from mundial.notificaciones import telegram
from mundial.persistencia import bd, esquema


def test_trocear_respeta_limite_y_lineas():
    texto = "\n".join(f"línea {i}" for i in range(100))
    trozos = telegram._trocear(texto, 200)
    assert all(len(t) <= 200 for t in trozos)
    assert "\n".join(trozos) == texto


def test_enviar_un_mensaje():
    solicitudes = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(solicitud)
        return httpx.Response(200, json={"ok": True})

    cliente = telegram.ClienteTelegram("TOKEN123", transporte=httpx.MockTransport(responder))
    enviados = cliente.enviar("42", "<b>hola</b>")
    assert enviados == 1
    assert "/botTOKEN123/sendMessage" in str(solicitudes[0].url)
    import json

    cuerpo = json.loads(solicitudes[0].content)
    assert cuerpo["chat_id"] == "42"
    assert cuerpo["parse_mode"] == "HTML"


def test_enviar_trocea_mensajes_largos():
    contador = {"n": 0}

    def responder(solicitud):
        contador["n"] += 1
        return httpx.Response(200, json={"ok": True})

    cliente = telegram.ClienteTelegram("T", transporte=httpx.MockTransport(responder))
    texto = "\n".join("x" * 100 for _ in range(60))  # ~6000 chars
    assert cliente.enviar("42", texto) == contador["n"] >= 2


def test_obtener_chat_id():
    def responder(solicitud):
        return httpx.Response(200, json={
            "ok": True,
            "result": [
                {"message": {"chat": {"id": 111}, "text": "viejo"}},
                {"message": {"chat": {"id": 222}, "text": "hola"}},
            ],
        })

    cliente = telegram.ClienteTelegram("T", transporte=httpx.MockTransport(responder))
    assert cliente.obtener_chat_id() == "222"


def preparar_bd_completa(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.executescript(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, fase, grupo, jornada,
                                estadio, estado)
           VALUES (1, '2026-06-12T19:00:00Z', 'Mexico', 'South Africa',
                   'GROUP_STAGE', 'GROUP_A', 1, NULL, 'TIMED');
           INSERT INTO partidos(id, fecha_utc, local, visitante, estado,
                                goles_local, goles_visitante)
           VALUES (2, '2026-06-11T19:00:00Z', 'Brazil', 'Scotland', 'FINISHED', 1, 0);
           INSERT INTO predicciones
             (partido_id, creado_en, marcador, p_local, p_empate, p_visitante,
              p_local_modelo, p_empate_modelo, p_visitante_modelo,
              p_local_mercado, p_empate_mercado, p_visitante_mercado)
           VALUES (2, '2026-06-11T10:00:00+00:00', '2-0', 0.7, 0.2, 0.1,
                   0.75, 0.15, 0.10, 0.65, 0.22, 0.13);
           INSERT INTO ratings VALUES ('Mexico', '2026-06-11', 0.5, 0.3);
           INSERT INTO ratings VALUES ('South Africa', '2026-06-11', -0.1, -0.2);
           INSERT INTO modelo_meta VALUES ('2026-06-11', 0.1, 0.23, -0.06, 9000, 200,
                                           -100.0, 'dc-1.0');"""
    )
    conexion.commit()
    return conexion


def test_armar_resumen_con_partidos_y_resultados(tmp_path):
    conexion = preparar_bd_completa(tmp_path)
    resumen = telegram.armar_resumen(conexion, fecha="2026-06-12")
    assert "Mexico vs South Africa" in resumen
    assert "1X2" in resumen
    assert "Brazil 1-0 Scotland" in resumen
    assert "❌" in resumen  # predijo 2-0 pero el 1X2 sí... el marcador exacto falló
    assert "✅" in resumen  # acierto 1X2 (local ganó, p_local era máxima)


def test_armar_resumen_dia_vacio(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    assert telegram.armar_resumen(conexion, fecha="2026-07-30") is None
