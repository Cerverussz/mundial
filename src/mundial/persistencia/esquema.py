"""Esquema de la base local. Idempotente."""
from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS equipos(
  nombre TEXT PRIMARY KEY,
  tla TEXT,
  confederacion TEXT
);
CREATE TABLE IF NOT EXISTS estadios(
  nombre TEXT PRIMARY KEY,
  ciudad TEXT, pais TEXT,
  altitud_m REAL, lat REAL, lon REAL, tz TEXT
);
CREATE TABLE IF NOT EXISTS partidos(
  id INTEGER PRIMARY KEY,
  fecha_utc TEXT NOT NULL,
  local TEXT NOT NULL,
  visitante TEXT NOT NULL,
  fase TEXT, grupo TEXT, jornada INTEGER,
  estadio TEXT,
  estado TEXT,
  goles_local INTEGER, goles_visitante INTEGER,
  id_fifa TEXT,
  fuente TEXT
);
CREATE TABLE IF NOT EXISTS resultados_historicos(
  fecha TEXT NOT NULL,
  local TEXT NOT NULL,
  visitante TEXT NOT NULL,
  goles_local INTEGER NOT NULL,
  goles_visitante INTEGER NOT NULL,
  torneo TEXT, ciudad TEXT, pais TEXT,
  neutral INTEGER NOT NULL,
  PRIMARY KEY(fecha, local, visitante)
);
CREATE TABLE IF NOT EXISTS ratings(
  equipo TEXT NOT NULL,
  fecha_ajuste TEXT NOT NULL,
  ataque REAL NOT NULL,
  defensa REAL NOT NULL,
  PRIMARY KEY(equipo, fecha_ajuste)
);
CREATE TABLE IF NOT EXISTS modelo_meta(
  fecha_ajuste TEXT PRIMARY KEY,
  mu REAL, ventaja_local REAL, rho REAL,
  n_partidos INTEGER, n_equipos INTEGER,
  log_verosimilitud REAL,
  version TEXT
);
CREATE TABLE IF NOT EXISTS cuotas(
  partido_id INTEGER NOT NULL,
  capturado_en TEXT NOT NULL,
  fuente TEXT NOT NULL,
  casa TEXT NOT NULL,
  mercado TEXT NOT NULL,
  local REAL, empate REAL, visitante REAL,
  PRIMARY KEY(partido_id, capturado_en, fuente, casa, mercado)
);
CREATE TABLE IF NOT EXISTS archivos_cargados(
  ruta TEXT PRIMARY KEY,
  cargado_en TEXT
);
CREATE TABLE IF NOT EXISTS eventos_bsd(
  partido_id INTEGER PRIMARY KEY,
  evento_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bajas(
  partido_id INTEGER NOT NULL,
  equipo TEXT NOT NULL,
  jugador TEXT NOT NULL,
  estado TEXT,
  razon TEXT,
  ai_score REAL,
  capturado_en TEXT NOT NULL,
  PRIMARY KEY(partido_id, equipo, jugador, capturado_en)
);
CREATE TABLE IF NOT EXISTS predicciones(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  partido_id INTEGER NOT NULL,
  creado_en TEXT NOT NULL,
  commit_datos TEXT,
  version_modelo TEXT,
  marcador TEXT,
  p_local REAL, p_empate REAL, p_visitante REAL,
  p_local_modelo REAL, p_empate_modelo REAL, p_visitante_modelo REAL,
  p_local_mercado REAL, p_empate_mercado REAL, p_visitante_mercado REAL,
  matriz_json TEXT,
  confianza TEXT,
  razones_confianza TEXT,
  factores_json TEXT,
  valor_flags TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS predicciones_unicas
  ON predicciones(partido_id, creado_en);
CREATE TABLE IF NOT EXISTS cuotas_mercado(
  partido_id INTEGER NOT NULL,
  capturado_en TEXT NOT NULL,
  fuente TEXT NOT NULL,
  casa TEXT NOT NULL,
  mercado TEXT NOT NULL,
  seleccion TEXT NOT NULL,
  cuota REAL NOT NULL,
  PRIMARY KEY(partido_id, capturado_en, fuente, casa, mercado, seleccion)
);
CREATE TABLE IF NOT EXISTS archivos_cargados_mercados(
  ruta TEXT PRIMARY KEY,
  cargado_en TEXT
);
CREATE TABLE IF NOT EXISTS apuestas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  partido_id INTEGER NOT NULL,
  creado_en TEXT NOT NULL,
  origen TEXT NOT NULL,
  mercado TEXT NOT NULL,
  seleccion TEXT NOT NULL,
  linea REAL,
  cuota REAL NOT NULL,
  casa TEXT,
  p_modelo REAL, p_mercado REAL, margen REAL,
  estado TEXT NOT NULL DEFAULT 'pendiente',
  retorno_flat REAL,
  stake_kelly REAL, retorno_kelly REAL,
  clv REAL,
  commit_datos TEXT,
  UNIQUE(partido_id, origen, mercado, seleccion, linea)
);
CREATE TABLE IF NOT EXISTS xg(
  partido_id INTEGER PRIMARY KEY,
  xg_local REAL, xg_visitante REAL,
  fuente TEXT, capturado_en TEXT
);
CREATE TABLE IF NOT EXISTS tiros(
  partido_id INTEGER NOT NULL,
  indice INTEGER NOT NULL,
  es_local INTEGER, minuto INTEGER, jugador_id INTEGER,
  xg REAL, xgot REAL, tipo TEXT, x REAL, y REAL,
  PRIMARY KEY(partido_id, indice)
);
CREATE TABLE IF NOT EXISTS resultados_wc(
  match_id TEXT PRIMARY KEY,
  anio INTEGER, fase TEXT, es_grupos INTEGER, es_eliminacion INTEGER,
  fecha TEXT, local TEXT, visitante TEXT,
  goles90_local INTEGER, goles90_visitante INTEGER,
  goles_final_local INTEGER, goles_final_visitante INTEGER,
  prorroga INTEGER, penales INTEGER
);
CREATE TABLE IF NOT EXISTS config(
  clave TEXT PRIMARY KEY,
  valor TEXT
);
"""


def _migrar(conexion: sqlite3.Connection) -> None:
    columnas = {f["name"] for f in conexion.execute("PRAGMA table_info(predicciones)")}
    if "mercados_json" not in columnas:
        conexion.execute("ALTER TABLE predicciones ADD COLUMN mercados_json TEXT")


def crear(conexion: sqlite3.Connection) -> None:
    conexion.executescript(DDL)
    _migrar(conexion)
    conexion.commit()
