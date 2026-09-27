import json
import random
import uuid
from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify

app = Flask(__name__)
app.secret_key = "pole_chudes_secret_key"

SERVER_RUN_ID = str(uuid.uuid4())

PLAYER_CLASSES = [
    {"name": "Кругладин",   "folder": "Guard"},
    {"name": "Круглумник",  "folder": "Science"},
    {"name": "Шарантюрист", "folder": "Adventurer"},
]

ITEM_TYPES = {
    "1lvl":  {"points": 5,   "spin_chance": 0.30, "variants": ["1lvl1", "1lvl2", "1lvl3"]},
    "2lvl":  {"points": 15,  "spin_chance": 0.25, "variants": ["2lvl1", "2lvl2", "2lvl3"]},
    "3lvl":  {"points": 50,  "spin_chance": 0.05, "variants": ["3lvl1", "3lvl2", "3lvl3"]},
    "full":  {"points": 100, "spin_chance": 0.0,  "variants": ["full"]},
    "open":  {"points": 20,  "spin_chance": 0.12, "variants": ["open"]},
    "loose": {"points": 0,   "spin_chance": 0.03, "variants": ["loose"]},
    "skip":  {"points": 0,   "spin_chance": 0.05, "variants": ["skip"]},
}

HUMAN_LABELS = {
    "1lvl":  "Предмет 1 уровня",
    "2lvl":  "Предмет 2 уровня",
    "3lvl":  "Предмет 3 уровня",
    "full":  "Награда за слово",
    "open":  "Открыватель буквы",
    "loose": "Разоритель",
    "skip":  "Пропуск хода",
}

ALL_VARIANTS = []
for t, info in ITEM_TYPES.items():
    if t == "full":
        continue
    for v in info["variants"]:
        ALL_VARIANTS.append({"type": t, "variant": v})


def load_words():
    with open("words.json", "r", encoding="utf-8") as f:
        return json.load(f)


def init_game():
    session.clear()

    all_words = load_words()
    random.shuffle(all_words)
    session["word_queue"] = all_words

    session["players"] = [
        {"name": c["name"], "folder": c["folder"], "inventory": []}
        for c in PLAYER_CLASSES
    ]
    session["current_player_idx"] = 0
    session["game_over"] = False
    session["winner"] = None
    session["sound_trigger"] = None
    session["pending_item"] = None

    next_round()

    session["server_run_id"] = SERVER_RUN_ID
    session.modified = True


def next_round():
    queue = session.get("word_queue", [])

    if not queue:
        session["game_over"] = True
        players = session["players"]

        def total_score(p):
            return sum(ITEM_TYPES[it["type"]]["points"] for it in p.get("inventory", []))
        best_player = max(players, key=total_score)
        session["winner"] = f"{best_player['name']} (Абсолютный чемпион со счетом {total_score(best_player)} б.!)"
        session["word"] = ""
        session["hint"] = "Все слова разгаданы!"
        session["guessed_letters"] = []
    else:
        chosen = queue.pop(0)
        session["word_queue"] = queue
        session["word"] = chosen["word"].upper()
        session["hint"] = chosen["hint"]
        session["guessed_letters"] = []
        session["round_finished"] = False

    session["pending_item"] = None
    session.modified = True


def get_display_word():
    if not session.get("word"):
        return ""
    return " ".join([l if l in session["guessed_letters"] else "_" for l in session["word"]])


def player_total_score(player):
    return sum(ITEM_TYPES[it["type"]]["points"] for it in player.get("inventory", []))


def roll_item():
    r = random.random()
    cumulative = 0.0
    # ВАЖНО: сумма всех spin_chance должна быть <= 1.0
    order = ["loose", "skip", "open", "3lvl", "2lvl", "1lvl"]
    for t in order:
        cumulative += ITEM_TYPES[t]["spin_chance"]
        if r < cumulative:
            variant = random.choice(ITEM_TYPES[t]["variants"])
            return {"type": t, "variant": variant}
    # fallback — самый частый предмет
    variant = random.choice(ITEM_TYPES["1lvl"]["variants"])
    return {"type": "1lvl", "variant": variant}


def item_points(item):
    return ITEM_TYPES[item["type"]]["points"]


def item_label(item):
    return HUMAN_LABELS[item["type"]]


def add_item(player, item):
    if item["type"] == "loose":
        # разоритель: оставляем только сами разорители (по старой логике)
        player["inventory"] = [it for it in player.get("inventory", []) if it["type"] == "loose"]
    player.setdefault("inventory", []).append({
        "type": item["type"],
        "variant": item["variant"],
        "points": item_points(item),
        "label": item_label(item),
    })


def remove_all_non_loose(player):
    player["inventory"] = [it for it in player.get("inventory", []) if it["type"] == "loose"]


@app.route("/")
def index():
    if not session.get("started"):
        return render_template("intro.html")

    if session.get("server_run_id") != SERVER_RUN_ID:
        init_game()

    sound_trigger = session.get("sound_trigger")
    session["sound_trigger"] = None

    players_view = []
    for p in session["players"]:
        players_view.append({
            "name": p["name"],
            "folder": p["folder"],
            "inventory": p.get("inventory", []),
            "score": player_total_score(p),
        })

    current_player = session["players"][int(session["current_player_idx"])]

    return render_template(
        "index.html",
        hint=session["hint"],
        display_word=get_display_word(),
        players=players_view,
        current_idx=session["current_player_idx"],
        game_over=session["game_over"],
        winner=session["winner"],
        sound_trigger=sound_trigger,
        round_finished=session.get("round_finished", False),
        words_left=len(session.get("word_queue", [])),
        guessed_letters=session.get("guessed_letters", []),
        wheel_folder=current_player["folder"],
        wheel_variants=ALL_VARIANTS,
    )


@app.route("/start_game", methods=["POST"])
def start_game():
    init_game()
    session["started"] = True
    session.modified = True
    return jsonify({"success": True})


@app.route("/next_word", methods=["POST"])
def next_word_route():
    if not session.get("game_over"):
        next_round()
    return redirect(url_for("index"))


@app.route("/spin", methods=["POST"])
def spin():
    if session.get("game_over") or session.get("round_finished"):
        return jsonify({"error": "Действие заблокировано"}), 400

    item = roll_item()

    variant_index = next(
        (i for i, v in enumerate(ALL_VARIANTS) if v["variant"] == item["variant"]),
        0
    )

    session["pending_item"] = item
    session.modified = True

    return jsonify({
        "variant": item["variant"],
        "type": item["type"],
        "type_label": HUMAN_LABELS[item["type"]],
        "variant_index": variant_index,
        "duration": random.randint(6000, 8000)
    })


@app.route("/apply_spin_effect", methods=["POST"])
def apply_spin_effect():
    item = session.get("pending_item")
    idx = int(session["current_player_idx"])
    players = list(session["players"])

    if not item:
        return jsonify({"success": True, "force_end": False})

    if item["type"] == "loose":
        flash(f"💥 {players[idx]['name']} — РАЗОРИТЕЛЬ! Инвентарь опустошён.")
        add_item(players[idx], item)
        session["sound_trigger"] = "wrong"
        session["current_player_idx"] = (idx + 1) % 3
        session["players"] = players
        session["pending_item"] = None
        session.modified = True
        return jsonify({"success": True, "force_end": True})

    if item["type"] == "skip":
        flash(f"⏭ {players[idx]['name']} — ПРОПУСК ХОДА!")
        session["sound_trigger"] = "wrong"
        session["current_player_idx"] = (idx + 1) % 3
        session["players"] = players
        session["pending_item"] = None
        session.modified = True
        return jsonify({"success": True, "force_end": True})

    if item["type"] == "open":
        # === ОТКРЫВАТЕЛЬ БУКВЫ ===
        word = session.get("word", "")
        guessed = session.get("guessed_letters", [])
        closed_letters = [l for l in set(word) if l not in guessed]

        if closed_letters:
            opened = random.choice(closed_letters)
            guessed.append(opened)
            session["guessed_letters"] = guessed
            flash(f"🔓 {players[idx]['name']} — ОТКРЫВАТЕЛЬ БУКВЫ! Открыта буква «{opened}».")
            session["sound_trigger"] = "right"

            add_item(players[idx], item)
            session["players"] = players
            session["pending_item"] = None
            session.modified = True

            # Если слово собралось — просто завершаем раунд, full НЕ начисляем
            if all(l in guessed for l in word):
                session["round_finished"] = True
                flash(f"🎉 Раунд окончен! {players[idx]['name']} собрал слово!")
                if not session.get("word_queue"):
                    next_round()

            return jsonify({"success": True, "force_end": True})
        else:
            flash(f"🔓 {players[idx]['name']} — ОТКРЫВАТЕЛЬ БУКВЫ, но открывать нечего.")
            add_item(players[idx], item)
            session["players"] = players
            session["pending_item"] = None
            session.modified = True
            return jsonify({"success": True, "force_end": True})

    # Все остальные предметы (1lvl/2lvl/3lvl) попадают в инвентарь при угадывании буквы
    return jsonify({"success": True, "force_end": False})


def check_word_completion():
    """
    Вызывается после угадывания буквы.
    Если слово собрано — завершаем раунд. full за это НЕ начисляем.
    """
    if all(l in session["guessed_letters"] for l in session["word"]):
        session["round_finished"] = True
        idx = int(session["current_player_idx"])
        flash(f"🎉 Раунд окончен! {session['players'][idx]['name']} угадал слово!")
        if not session.get("word_queue"):
            next_round()


@app.route("/guess_letter", methods=["POST"])
def guess_letter():
    if session.get("game_over") or session.get("round_finished"):
        return jsonify({"ok": False, "reason": "blocked"}), 400

    letter = request.form.get("letter", "").upper().strip()
    idx = int(session["current_player_idx"])
    players = list(session["players"])
    pending = session.get("pending_item")

    if not letter or len(letter) != 1:
        return jsonify({"ok": False, "reason": "bad_letter"}), 400

    if letter in session["guessed_letters"]:
        return jsonify({"ok": False, "reason": "already"}), 400

    session["guessed_letters"].append(letter)
    sound = None

    if letter in session["word"]:
        sound = "right"
        if pending:
            add_item(players[idx], pending)
            session["pending_item"] = None
        session["players"] = players
        check_word_completion()
    else:
        sound = "wrong"
        session["pending_item"] = None

    session["current_player_idx"] = (idx + 1) % 3
    session["players"] = players
    session.modified = True
    return jsonify({"ok": True, "sound": sound})


@app.route("/plus_sector", methods=["POST"])
def plus_sector():
    return redirect(url_for("index"))


@app.route("/guess_word", methods=["POST"])
def guess_word():
    if session.get("game_over") or session.get("round_finished"):
        return jsonify({"ok": False, "reason": "blocked"}), 400

    entire_word = request.form.get("entire_word", "").upper().strip()
    idx = int(session["current_player_idx"])
    players = list(session["players"])

    if entire_word == session["word"]:
        session["round_finished"] = True
        item = {"type": "full", "variant": "full"}
        add_item(players[idx], item)
        sound = "full"
        session["sound_trigger"] = "full"
        # открываем все буквы в display_word
        session["guessed_letters"] = list(set(session["word"]))
        session["players"] = players
        flash(f"🎉 {players[idx]['name']} угадал слово целиком! (+100 б.)")
        if not session.get("word_queue"):
            next_round()
    else:
        sound = "wrong"
        session["sound_trigger"] = "wrong"

    session["pending_item"] = None
    session["current_player_idx"] = (idx + 1) % 3
    session["players"] = players
    session.modified = True
    return jsonify({"ok": True, "sound": sound})


@app.route("/reset")
def reset():
    init_game()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)