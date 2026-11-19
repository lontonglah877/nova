"""Doctor-cheatsheet → flashcards: a pure, offline way to seed study cards."""

from __future__ import annotations

# Each tuple: (topic, front, back, source)
SEED_CARDS = [
    ("Kolangitis", "Apa definisi kolangitis?", "Infeksi dan inflamasi duktus biliaris, biasanya obstruktif.", "Baja internal"),
    ("Kolangitis", "Trias Charcot pada kolangitis?", "Demam + nyeri kuadran kanan atas + ikterus.", "Baja internal"),
    ("Kolangitis", "Pentad Reynolds menambahkan apa?", "Hipotensi dan penurunan kesadaran (syok sepsis).", "Baja internal"),
    ("Koledokolitiasis", "Gejala khas batu duktus koledokus?", "Nyeri bilier kolik + ikterus fluktuatif + demam bila kolangitis.", "Baja internal"),
    ("Koledokolitiasis", "Pemeriksaan awal pilihan?", "USG abdomen; MRCP bila USG tidak konklusif.", "Baja internal"),
]


def seed(conn, topic_service, card_service):
    made, dedup = 0, 0
    topic_ids = {}
    for topic, front, back, source in SEED_CARDS:
        if topic not in topic_ids:
            topic_ids[topic] = topic_service(conn, {"name": topic})["id"]
        res = card_service(conn, {
            "front": front, "back": back, "source": source,
            "topic_id": topic_ids[topic],
            "idempotency_key": f"seed:{topic}:{front[:40]}",
        })
        if res.get("deduplicated"):
            dedup += 1
        else:
            made += 1
    return {"cards_created": made, "cards_deduplicated": dedup}
