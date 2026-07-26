"""Chat-toxicity scoring from an OpenDota wordcloud.

A self-contained subsystem that used to live inside analysis.py: multilingual
lexicons, an exact-token scan of the player's own chat (`my_word_counts`), and a
0-100 score with a readable band. It only ever produced a handful of metrics
fields, so it lifts out cleanly — analysis.py now just merges :func:`score`'s
result into the player's data dict.

Exact-token match (not substring) so "ass" never fires on "assist"/"class".
"""

# ---- lexicons (case-folded exact tokens) ----
# MULTILINGUAL: Dota chat is heavily Russian / Spanish / Portuguese / Filipino /
# Chinese even on NA servers, so each list extends its English base with the
# common transliterated (and some native-script) terms that actually appear in
# this pool. Ambiguous short tokens that collide with real words ("hp", "dno",
# "cai", "lox", "tang") are deliberately left out.
_SLUR_EN = {"retard", "retarded", "retards", "faggot", "fag", "fags", "nigger",
            "nigga", "niggers", "tranny", "kys", "cunt", "spastic", "autist"}
_SLUR_INTL = {
    "pidor", "pidoras", "pidr", "пидор", "пидорас",              # RU
    "maricon", "maricón", "viado", "veado", "bicha", "macaco",   # ES/PT homophobic/racist
    "retrasado", "retardado", "mongol", "mongolico", "mongólico",  # ableist (≈ "retard")
    "mongoloide", "nmsl",                                        # CN harassment
}
TOX_SLUR = _SLUR_EN | _SLUR_INTL

_CURSE_EN = {"fuck", "fucking", "fuckin", "fucked", "fck", "shit", "shitty",
             "bitch", "asshole", "ass", "dick", "bastard", "piss", "wtf",
             "stfu", "gtfo", "bullshit", "dumbass", "jackass", "prick", "wanker"}
_CURSE_INTL = {
    "cyka", "cyca", "suka", "blyat", "blyad", "huy", "nahui", "naxui",  # RU
    "pizda", "pizdec", "mudak", "сука", "блять", "блядь", "хуй", "мудак",
    "puta", "puto", "mierda", "verga", "cabron", "cabrón", "pendejo",   # ES
    "hijueputa", "hijodeputa", "hpta", "malparido", "gonorrea", "culero",
    "chinga", "chingar", "chingada", "ctm", "conchatumadre",
    "caralho", "krl", "porra", "merda", "fdp", "arrombado", "corno", "cacete",  # PT
    "putangina", "tangina", "tanginamo", "gago", "pakyu", "kingina",   # FIL
    "cnm", "shabi", "傻逼", "你妈",                                     # CN
}
TOX_CURSE = _CURSE_EN | _CURSE_INTL

_FLAME_EN = {"report", "reported", "noob", "noobs", "nub", "trash", "garbage",
             "idiot", "idiots", "stupid", "ez", "uninstall", "throw", "throwing",
             "thrower", "feed", "feeder", "feeders", "feeding", "boosted",
             "braindead", "dogshit", "clown", "clowns", "moron", "morons",
             "dumb", "delete", "useless", "coward", "loser", "losers", "rage",
             "tilt", "tilted", "cancer"}
_FLAME_INTL = {
    "rak", "loh", "debil", "slil", "chmo", "лох", "рак", "дебил", "нуб", "чмо",  # RU
    "idiota", "estupido", "estúpido", "imbecil", "imbécil", "basura", "manco",  # ES
    "inutil", "inútil", "burro", "bobo", "tarado",
    "lixo", "otario", "otário", "vagabundo",                    # PT
    "tanga", "ulol",                                            # FIL
    "sb", "laji", "智障", "白痴", "弱智", "垃圾",                 # CN (trash/idiot)
}
TOX_FLAME = _FLAME_EN | _FLAME_INTL

TOX_WEIGHTS = {"slur": 10, "curse": 3, "flame": 1}
# Bands calibrated to the actual LD2L pool: routine Dota chat carries a lot of
# report/ez/gg, so the median player sits mid-scale — "Toxic" is reserved for
# the genuinely heavy end (top ~20-25%), not everyone.
TOX_BANDS = [(65, "Toxic"), (40, "Salty"), (15, "Mild")]  # else Clean
CHAT_PRIOR = 300   # neutral pseudo-words: shrinks thin-sample scores toward 0
TOX_SCALE = 0.7    # weighted-rate → 0-100 score multiplier (cap 100)

DISPLAY_STOPWORDS = {
    "the", "a", "an", "to", "of", "and", "or", "is", "are", "was", "in", "on",
    "it", "this", "that", "you", "u", "i", "im", "me", "my", "we", "he", "she",
    "they", "them", "for", "so", "no", "yes", "not", "do", "dont", "did", "get",
    "got", "go", "going", "can", "just", "now", "then", "here", "there", "what",
    "why", "how", "who", "when", "if", "but", "with", "have", "has", "had", "be",
    "been", "will", "ok", "okay", "yeah", "yea", "lol", "haha", "hi", "hey",
    "hello", "gg", "glhf", "wp", "ggwp", "glgl", "thx", "ty", "guys", "come",
    "need", "pls", "plz", "he", "your", "our", "us", "all", "up", "back",
}


def classify(word):
    """Severity tier of a single chat token, or None if it's not flagged."""
    if word in TOX_SLUR:
        return "slur"
    if word in TOX_CURSE:
        return "curse"
    if word in TOX_FLAME:
        return "flame"
    return None


def score(wordcloud):
    """Chat + toxicity metrics from an OpenDota wordcloud section.

    Returns a dict to merge into the player's data. Exact-token scan over the
    player's own chat, weighted by config severity tiers and normalised to a
    0-100 score with a readable band. On private/empty chat only
    ``{"private_chat": True}`` is returned; the caller's defaults cover the rest.
    Heuristic and transparent — the report shows the raw flagged words.
    """
    counts = (wordcloud or {}).get("my_word_counts") if isinstance(wordcloud, dict) else None
    if not counts:
        return {"private_chat": True}

    norm = {}
    for w, c in counts.items():
        key = str(w).strip().lower()
        if not key:
            continue
        try:
            norm[key] = norm.get(key, 0) + int(c)
        except (TypeError, ValueError):
            continue
    total = sum(norm.values())
    if not total:
        return {"chat_total_words": total, "chat_unique_words": len(norm),
                "private_chat": True}

    # readable mini word cloud: drop stopwords / single chars, keep top talkers
    cloud = [(w, c) for w, c in norm.items()
             if w not in DISPLAY_STOPWORDS and len(w) > 1]
    cloud.sort(key=lambda kv: -kv[1])

    # toxicity scan over the raw counts (stopwords are irrelevant here)
    hits, breakdown, weighted = {}, {"flame": 0, "curse": 0, "slur": 0}, 0
    for w, c in norm.items():
        cat = classify(w)
        if cat:
            hits[w] = c
            breakdown[cat] += c
            weighted += c * TOX_WEIGHTS[cat]

    # Weighted toxic tokens per 1000 chat words, shrunk toward 0 for thin
    # samples via a neutral prior (a couple of hits in 40 words isn't a read),
    # then scaled to 0-100. Slurs already count 10x in the weight, so heavy slur
    # users rise on their own — no artificial floor that would over-promote the
    # many players with an occasional slur token.
    rate = weighted / (total + CHAT_PRIOR) * 1000
    score_val = min(100, round(rate * TOX_SCALE))
    label = "Clean"
    for thresh, lb in TOX_BANDS:
        if score_val >= thresh:
            label = lb
            break

    return {
        "chat_total_words": total,
        "chat_unique_words": len(norm),
        "chat_top_words": cloud[:24],
        "toxicity_hits": sorted(hits.items(), key=lambda kv: -kv[1]),
        "toxicity_breakdown": breakdown,
        "toxicity_score": score_val,
        "toxicity_label": label,
    }
