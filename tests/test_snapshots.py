from datetime import datetime, timezone

from mundial.ingesta import snapshots


def test_escribir_y_leer_roundtrip(tmp_path):
    momento = datetime(2026, 6, 11, 14, 30, 5, tzinfo=timezone.utc)
    payload = {"hola": "mundo", "n": [1, 2, 3]}
    ruta = snapshots.escribir_snapshot("bsd", payload, momento=momento, base=tmp_path)
    assert ruta == tmp_path / "2026-06-11" / "143005Z-bsd.json.gz"
    contenido = snapshots.leer_snapshot(ruta)
    assert contenido["fuente"] == "bsd"
    assert contenido["capturado_en"] == "2026-06-11T14:30:05+00:00"
    assert contenido["payload"] == payload


def test_ultimo_snapshot_vacio(tmp_path):
    assert snapshots.ultimo_snapshot("bsd", base=tmp_path) is None


def test_ultimo_snapshot_encuentra_el_mas_reciente(tmp_path):
    t1 = datetime(2026, 6, 11, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 11, 14, 0, 0, tzinfo=timezone.utc)
    snapshots.escribir_snapshot("odds-api", {}, momento=t1, base=tmp_path)
    snapshots.escribir_snapshot("odds-api", {}, momento=t2, base=tmp_path)
    snapshots.escribir_snapshot(
        "bsd", {}, momento=datetime(2026, 6, 12, 9, 0, 0, tzinfo=timezone.utc), base=tmp_path
    )
    assert snapshots.ultimo_snapshot("odds-api", base=tmp_path) == t2
