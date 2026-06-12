from mundial.ingesta import mundiales
from mundial.persistencia import bd, esquema

MATCHES_CSV = """key_id,tournament_id,tournament_name,match_id,match_name,stage_name,group_name,group_stage,knockout_stage,replayed,replay,match_date,match_time,stadium_id,stadium_name,city_name,country_name,home_team_id,home_team_name,home_team_code,away_team_id,away_team_name,away_team_code,score,home_team_score,away_team_score,home_team_score_margin,away_team_score_margin,extra_time,penalty_shootout,score_penalties,home_team_score_penalties,away_team_score_penalties,result,home_team_win,away_team_win,draw
1,WC-2014,x,M-2014-60,a,round of sixteen,,0,1,0,0,2014-06-28,17:00,S-1,s,c,p,T-1,Brazil,BRA,T-2,Chile,CHI,1–1,1,1,0,0,1,1,3-2,3,2,home team win,1,0,0
2,WC-2014,x,M-2014-01,b,group stage,Group A,1,0,0,0,2014-06-12,17:00,S-1,s,c,p,T-1,Brazil,BRA,T-3,Croatia,CRO,3–1,3,1,2,-2,0,0,0-0,0,0,home team win,1,0,0
"""

GOALS_CSV = """key_id,goal_id,tournament_id,tournament_name,match_id,match_name,match_date,stage_name,group_name,team_id,team_name,team_code,home_team,away_team,player_id,family_name,given_name,shirt_number,player_team_id,player_team_name,player_team_code,minute_label,minute_regulation,minute_stoppage,match_period,own_goal,penalty
1,G-1,WC-2014,x,M-2014-60,a,2014-06-28,r16,,T-1,Brazil,BRA,1,0,P-1,A,B,10,T-1,Brazil,BRA,18',18,0,first half,0,0
2,G-2,WC-2014,x,M-2014-60,a,2014-06-28,r16,,T-2,Chile,CHI,0,1,P-2,C,D,9,T-2,Chile,CHI,32',32,0,first half,0,0
3,G-3,WC-2014,x,M-2014-60,a,2014-06-28,r16,,T-1,Brazil,BRA,1,0,P-3,E,F,7,T-1,Brazil,BRA,108',108,0,extra time second half,0,0
4,G-4,WC-2014,x,M-2014-01,b,2014-06-12,g,Group A,T-3,Croatia,CRO,0,1,P-4,G,H,5,T-3,Croatia,CRO,11',11,0,first half,1,0
"""


def test_carga_reconstruye_score_90(tmp_path):
    (tmp_path / "matches.csv").write_text(MATCHES_CSV)
    (tmp_path / "goals.csv").write_text(GOALS_CSV)
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    n = mundiales.cargar(conexion, tmp_path / "matches.csv", tmp_path / "goals.csv")
    assert n == 2
    ko = conexion.execute("SELECT * FROM resultados_wc WHERE match_id='M-2014-60'").fetchone()
    # final con prórroga 1-1... el gol 108' NO cuenta para 90': score90 = 1-1
    assert (ko["goles90_local"], ko["goles90_visitante"]) == (1, 1)
    assert ko["prorroga"] == 1 and ko["penales"] == 1 and ko["es_eliminacion"] == 1
    grupo = conexion.execute("SELECT * FROM resultados_wc WHERE match_id='M-2014-01'").fetchone()
    # grupo sin prórroga: el marcador 90' es el final del matches.csv (3-1)
    assert (grupo["goles90_local"], grupo["goles90_visitante"]) == (3, 1)
    assert grupo["es_grupos"] == 1
