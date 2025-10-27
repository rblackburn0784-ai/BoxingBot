import random
def seeded(seed: int): r = random.Random(seed); return r
def weighted_choice(r: random.Random, items): # [(value, weight), ...]
    total = sum(w for _,w in items); pick = r.uniform(0,total); c=0
    for v,w in items:
        c += w
        if pick <= c: return v
