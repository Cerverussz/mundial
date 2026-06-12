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
    # Mercados para el partido 10 en dos momentos (>2h y reciente) → flag sostenido en over.
    # BSD siempre trae 1X2 junto a los demás mercados, así que se siembra también.
    for momento in ("2026-06-11T20:00:00+00:00", "2026-06-11T23:30:00+00:00"):
        for casa in ("pinnacle", "bet365"):
            conexion.execute(
                "INSERT INTO cuotas VALUES (10, ?, 'bsd', ?, '1x2', 1.95, 3.4, 4.0)",
                (momento, casa))
            for mercado_clave, seleccion, cuota in (
                ("draw_no_bet", "HOME", 1.55), ("draw_no_bet", "AWAY", 2.45),
                ("over_under_25", "over@2.5", 2.40), ("over_under_25", "under@2.5", 1.55),
            ):
                conexion.execute(
                    "INSERT INTO cuotas_mercado VALUES (10, ?, 'bsd', ?, ?, ?, ?)",
                    (momento, casa, mercado_clave, seleccion, cuota))
    conexion.commit()
    return conexion


PATRON_PRUEBA = {
    "id": "test_empate_j1",
    "familia": "test",
    "hipotesis": "empate barato en jornada 1",
    "filtro": {"jornada": 1},
    "mercado_objetivo": "1x2",
    "lado": "empate",
    "efecto": {"tasa": 0.35, "baseline": 0.28, "lift": 0.07},
    "n": 100, "p_adj_bh": 0.04, "ic95": [0.28, 0.42],
    "registrado_en_commit": "HEAD",
    "ventana_validez": ["2026-06-01", "2026-07-19"],
    "umbral_prob_implicita": 0.30,
    "estado": "en_papel",
}


def test_vigilar_alerta_patron(tmp_path):
    conexion = preparar_bd(tmp_path)
    telegram = TelegramFalso()
    vigilar.vigilar(conexion, telegram, "42", ahora=AHORA, ruta_estado=tmp_path / "n.json",
                    patrones_validados=[PATRON_PRUEBA])
    pre = next(m for m in telegram.mensajes if "Arranca" in m)
    assert "patrón pre-registrado" in pre.lower()
    apuesta = conexion.execute(
        "SELECT * FROM apuestas WHERE origen LIKE 'patron:%'").fetchone()
    assert apuesta is not None


def test_vigilar_guarda_xg(tmp_path):
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    conexion = preparar_bd(tmp_path)
    conexion.execute("INSERT INTO eventos_bsd VALUES (11, 8287)")
    conexion.commit()

    class BsdConStats:
        def estadisticas(self, evento_id):
            return json.loads((fixtures / "bsd_stats.json").read_text())

    vigilar.vigilar(conexion, TelegramFalso(), "42", ahora=AHORA,
                    ruta_estado=tmp_path / "n.json", cliente_bsd=BsdConStats())
    fila = conexion.execute("SELECT * FROM xg WHERE partido_id=11").fetchone()
    assert fila["xg_local"] == 1.41
    assert conexion.execute(
        "SELECT COUNT(*) c FROM tiros WHERE partido_id=11").fetchone()["c"] == 19


def test_vigilar_abre_y_liquida_apuestas(tmp_path):
    conexion = preparar_bd(tmp_path)
    registro = vigilar.vigilar(
        conexion, TelegramFalso(), "42", ahora=AHORA, ruta_estado=tmp_path / "n.json")
    n_apuestas = conexion.execute("SELECT COUNT(*) c FROM apuestas").fetchone()["c"]
    assert n_apuestas >= 1
    assert any("apuestas papel" in r for r in registro)


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
