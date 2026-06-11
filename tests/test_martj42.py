import httpx

from mundial.ingesta import martj42
from mundial.persistencia import bd, esquema

CSV_PRUEBA = """date,home_team,away_team,home_score,away_score,tournament,city,country,neutral
2024-07-14,Argentina,Colombia,1,0,Copa América,Miami Gardens,United States,TRUE
2025-03-20,Mexico,Canada,2,0,CONCACAF Nations League,Inglewood,United States,TRUE
2026-06-27,Panama,England,NA,NA,FIFA World Cup,East Rutherford,United States,TRUE
"""


def test_cargar_salta_filas_sin_marcador(tmp_path):
    ruta = tmp_path / "results.csv"
    ruta.write_text(CSV_PRUEBA)
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    n = martj42.cargar(conexion, ruta)
    assert n == 2
    fila = conexion.execute(
        "SELECT * FROM resultados_historicos WHERE local='Argentina'").fetchone()
    assert fila["goles_local"] == 1 and fila["neutral"] == 1


def test_descargar_usa_cache_reciente(tmp_path):
    ruta = tmp_path / "results.csv"
    ruta.write_text(CSV_PRUEBA)

    def responder(solicitud):
        raise AssertionError("No debería tocar la red con caché fresca")

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    assert martj42.descargar(ruta, http=cliente) == ruta


def test_descargar_baja_si_no_existe(tmp_path):
    ruta = tmp_path / "results.csv"

    def responder(solicitud):
        return httpx.Response(200, text=CSV_PRUEBA)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    martj42.descargar(ruta, http=cliente)
    assert "Argentina" in ruta.read_text()
