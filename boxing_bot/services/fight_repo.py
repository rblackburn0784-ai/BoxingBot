from .state import SESSIONS, save_sessions, session_to_dict, session_from_dict

def save_fight(state_dict):
    s=session_from_dict(state_dict) if isinstance(state_dict,dict) else state_dict
    SESSIONS[int(s.channel_id)]=s; save_sessions()

def load_fight(fid):
    try: s=SESSIONS.get(int(fid))
    except (TypeError,ValueError): s=None
    return session_to_dict(s) if s else None
