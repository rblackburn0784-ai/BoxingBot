import os
import random
import tempfile

from boxing_bot.models import Boxer, FighterState, FightSession
from boxing_bot.storage import v2db
from boxing_bot.services import game, tournaments
from boxing_bot.services.roster import get_boxer


def reset_db():
    for suffix in ("", "-wal", "-shm"):
        try: os.remove(str(v2db.DB_PATH)+suffix)
        except FileNotFoundError: pass
    v2db.init_db(); game.import_legacy_profiles()


def fake_session(red_name, blue_name, winner, method="Points", seed=123, channel_id=55):
    red=get_boxer(red_name); blue=get_boxer(blue_name)
    s=FightSession(channel_id=channel_id,rng_seed=seed,rng=random.Random(seed),red_raw=red,blue_raw=blue,red_eff=red,blue_eff=blue,
        A=FighterState(red,100),B=FighterState(blue,80))
    s.finished=True; s.winner=winner; s.winner_corner="Red" if winner and winner.lower()==red_name.lower() else "Blue" if winner else None; s.winner_type=method
    s.current_round=3
    s.kd_total={"A":0,"B":1}
    s.log=[{"round":1,"events":[{"attacker":red_name,"defender":blue_name,"damage":12},{"attacker":blue_name,"defender":red_name,"damage":7}]},
           {"round":2,"events":[{"attacker":red_name,"defender":blue_name,"damage":8}]}]
    return s


def main():
    reset_db()
    names=["comradetriplet","beluga_the_whale"]
    assert all(game.competitive_legal(n)[0] for n in names)
    game.link_boxer(names[0],1,101)
    assert game.get_owned_boxer(1,101)==names[0]
    try:
        game.link_boxer(names[1],1,101)
        raise AssertionError("duplicate ownership should fail")
    except ValueError: pass

    tid=tournaments.create_tournament(1,"V2 Test Cup",999,16)
    tournaments.register(tid,names[0]); tournaments.register(tid,names[1]); tournaments.start(tid,seed=9)
    assert not game.can_edit_boxer(names[0])[0]
    m=tournaments.pending_matches(tid)[0]
    s=fake_session(m['red_name'],m['blue_name'],m['red_name'],"TKO",seed=444,channel_id=77)
    fid=game.finalize_session(s,1)
    assert fid
    assert game.finalize_session(s,1) is None, "fight must be idempotent"
    t=tournaments.tournament(tid)
    assert t['status']=='complete' and t['champion_name'].lower()==m['red_name'].lower()
    champ=game.profile(m['red_name'])
    loser=game.profile(m['blue_name'])
    assert champ['stats']['fights']==1 and champ['stats']['wins']==1 and champ['stats']['tkos']==1
    assert champ['stats']['damage_for']==20 and loser['stats']['damage_for']==7
    assert champ['stats']['knockdowns_for']==1 and loser['stats']['knockdowns_against']==1
    assert champ['stats']['tournament_titles']==1
    assert champ['profile']['prestige']==1
    assert game.can_edit_boxer(m['red_name'])[0]
    report=tournaments.tournament_report(tid)
    assert report['bouts']==1 and report['tko']==1 and report['damage']==27 and report['knockdowns']==1
    codes={a['code'] for a in champ['achievements']}
    assert {'FIRST_BELL','FIRST_WIN','FIRST_STOPPAGE','CHAMPION'} <= codes
    # Achievement idempotency with NULL tournament_id
    with v2db.transaction() as con:
        game.evaluate_achievements(con,m['red_name'])
        game.evaluate_achievements(con,m['red_name'])
    rows=v2db.all_rows("SELECT code,COUNT(*) n FROM achievements WHERE boxer_name=? GROUP BY code HAVING n>1",(m['red_name'],))
    assert not rows
    print("V2 CORE: PASS")

if __name__=='__main__': main()
