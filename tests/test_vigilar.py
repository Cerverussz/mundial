import json
from datetime import datetime, timezone

from mundial.notificaciones import vigilar
from mundial.persistencia import bd, esquema

AHORA = datetime(2026, 6, 12, 0, 0, 0, tzinfo=timezone.utc)


class TelegramFalso:
    def __init__(self):
        self.mensajes = []

    def enviar(self, chat_id, texto):
        self.mensajes.append(texto)
        return 1


def preparar_bd(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.executescript(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, fase, jornada, estado)
           VALUES (10, '2026-06-12T02:00:00Z', 'South Korea', 'Czech Republic',
                   'GROUP_STAGE', 1, 'TIMED');
           INSERT INTO partidos(id, fecha_utc, local, visitante, estado,
                                goles_local, goles_visitante)
           VALUES (11, '2026-06-11T19:00:00Z', 'Mexico', 'South Africa', 'FINISHED', 2, 0);
           INSERT INTO partidos(id, fecha_utc, local, visitante, fase, estado)
           VALUES (12, '2026-06-13T19:00:00Z', 'Brazil', 'Scotland',
                   'GROUP_STAGE', 'TIMED');
           INSERT INTO predicciones
             (partido_id, creado_en, marcador, p_local, p_empate, p_visitante,
              p_local_modelo, p_empate_modelo, p_visitante_modelo,
              p_local_mercado, p_empate_mercado, p_visitante_mercado)
           VALUES (11, '2026-06-11T10:00:00+00:00', '2-0', 0.73, 0.18, 0.09,
                   0.80, 0.14, 0.06, 0.68, 0.21, 0.11);
           INSERT INTO ratings VALUES ('South Korea', '2026-06-11', 0.2, 0.1);
           INSERT INTO ratings VALUES ('Czech Republic', '2026-06-11', 0.1, 0.0);
           INSERT INTO modelo_meta VALUES ('2026-06-11', 0.1, 0.23, -0.06, 9000, 200,
                                           -100.0, 'dc-1.0');"""
    )
    conexion.commit()
    return conexion


def test_vigilar_envia_pre_y_post_sin_duplicar(tmp_path):
    conexion = preparar_bd(tmp_path)
    telegram = TelegramFalso()
    estado = tmp_path / "notificaciones.json"

    registro = vigilar.vigilar(conexion, telegram, "42", ahora=AHORA, ruta_estado=estado)
    assert len(telegram.mensajes) == 2
    pre = next(m for m in telegram.mensajes if "Arranca en" in m)
    assert "South Korea vs Czech Republic" in pre
    assert "2.0 h" in pre
    post = next(m for m in telegram.mensajes if "Final" in m)
    assert "Mexico 2-0 South Africa" in post
    assert "Pronóstico: <b>2-0</b>" in post
    assert "✅ 1X2" in post and "✅ marcador exacto" in post
    assert "73%" in post
    assert "1X2 1/1 (100%)" in post
    assert any("análisis enviado" in r for r in registro)

    # Segunda corrida: nada nuevo
    registro = vigilar.vigilar(conexion, telegram, "42", ahora=AHORA, ruta_estado=estado)
    assert len(telegram.mensajes) == 2
    assert registro == ["sin novedades"]
    guardado = json.loads(estado.read_text())
    assert guardado["pre"] == [10] and guardado["post"] == [11]


def test_vigilar_resultado_sin_pronostico(tmp_path):
    conexion = preparar_bd(tmp_path)
    conexion.execute("DELETE FROM predicciones")
    conexion.commit()
    telegram = TelegramFalso()
    vigilar.vigilar(conexion, telegram, "42", ahora=AHORA,
                    ruta_estado=tmp_path / "n.json")
    post = next(m for m in telegram.mensajes if "Final" in m)
    assert "sin pronóstico previo" in post


def test_vigilar_no_envia_fuera_de_ventana(tmp_path):
    conexion = preparar_bd(tmp_path)
    conexion.execute("DELETE FROM partidos WHERE id = 11")
    conexion.commit()
    telegram = TelegramFalso()
    temprano = datetime(2026, 6, 11, 20, 0, 0, tzinfo=timezone.utc)  # 6 h antes
    vigilar.vigilar(conexion, telegram, "42", ahora=temprano,
                    ruta_estado=tmp_path / "n.json")
    assert telegram.mensajes == []
