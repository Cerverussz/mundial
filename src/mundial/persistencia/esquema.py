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
"""


def crear(conexion: sqlite3.Connection) -> None:
    conexion.executescript(DDL)
    conexion.commit()
