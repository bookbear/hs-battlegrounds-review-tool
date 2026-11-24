import argparse
import glob
import gzip
import html
import json
import os
import re
import sys
import urllib.request


# バトルグラウンド種族定義（現行プール10種族 + ナーガ復帰時用ラベル）
BG_BASE_TRIBES = [
    "ABERRATION",
    "UNDEAD",
    "ELEMENTALS",
    "QUILLBOAR",
    "DRAGON",
    "MURLOC",
    "MECH",
    "DEMON",
    "PIRATE",
    "BEAST",
]
BG_TRIBE_LABELS = {
    "ABERRATION": "異形",
    "UNDEAD": "アンデッド",
    "ELEMENTALS": "エレメンタル",
    "QUILLBOAR": "キルボア",
    "DRAGON": "ドラゴン",
    "MURLOC": "マーロック",
    "MECH": "メカ",
    "DEMON": "悪魔",
    "PIRATE": "海賊",
    "BEAST": "獣",
    "NAGA": "ナーガ",
}
# HearthstoneJSON cards.json の race / races 表記用日本語ラベル
CARD_RACE_LABELS = {
    **BG_TRIBE_LABELS,
    "ALL": "すべて",
    "ELEMENTAL": "エレメンタル",
    "MECHANICAL": "メカ",
    "QUILBOAR": "キルボア",
}


def normalize_dark_gift_id(card_id):
    """エンチャントID等を基底の「悪夢の恵み」CardIDへ正規化する"""
    if not card_id:
        return ""
    m_edr = re.match(r"^EDR_100t(\d+)e\d*$", card_id)
    if m_edr:
        return f"BG36_MidGameEffect_000t{m_edr.group(1)}"
    if card_id.startswith("BG36_MidGameEffect_000t"):
        # 末尾の e / e2 / e3 を取り除いて基底スペルIDへ揃える
        return re.sub(r"e\d*$", "", card_id)
    return ""


def clean_card_text(raw_text):
    """HearthstoneJSON のカードテキストから制御文字・HTMLタグ・テンプレート表記を整形する"""
    if not raw_text:
        return ""
    text = raw_text.replace("[x]", "").replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s*\n+\s*", "", text)
    text = re.sub(r"（0[回枚]?）$", "", text).strip()
    return text


def fetch_card_catalog():
    """HTML生成時に HearthstoneJSON から悪夢の恵み・装飾品・ヒーロー名マスタを一括取得する"""
    url = "https://api.hearthstonejson.com/v1/latest/jaJP/cards.json"
    catalog = {"dark_gifts": {}, "by_dbf_id": {}, "by_card_id": {}}
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Encoding": "gzip",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            cards = json.loads(raw.decode("utf-8"))

        for c in cards:
            cid = c.get("id", "")
            dbf_id = c.get("dbfId")
            name = c.get("name", "")
            text = clean_card_text(c.get("text", ""))
            ctype = c.get("type", "")
            raw_races = c.get("races") or ([c["race"]] if c.get("race") else [])
            tribes = [CARD_RACE_LABELS.get(r, r) for r in raw_races if r]
            entry = {
                "id": cid,
                "name": name or cid,
                "text": text,
                "type": ctype,
                "tier": c.get("techLevel"),
                "cost": c.get("cost"),
                "atk": c.get("attack"),
                "hp": c.get("health"),
                "tribes": tribes,
                "hero_power_dbf_id": c.get("heroPowerDbfId"),
            }
            if dbf_id is not None and cid:
                catalog["by_dbf_id"][int(dbf_id)] = entry
            if cid and name:
                catalog["by_card_id"][cid] = entry

        # 基底スペル（SPELL）を優先して登録し、該当スペルが無いIDのみ ENCHANTMENT で補完
        dg_db = catalog["dark_gifts"]
        for card_type in ("SPELL", "ENCHANTMENT"):
            for c in cards:
                cid = c.get("id", "")
                if c.get("type") != card_type:
                    continue
                norm = normalize_dark_gift_id(cid)
                if not norm or norm in dg_db:
                    continue
                name = c.get("name", cid)
                text = clean_card_text(c.get("text", ""))
                dg_db[norm] = (name, text)
    except Exception as e:
        print(f"警告: HearthstoneJSON からカードマスタの取得に失敗しました（{e}）。CardIDで表示します。")
    return catalog


def find_latest_power_log():
    """Windowsの標準インストール先から最新のPower.logを自動検出する"""
    base_dir = r"C:\Program Files (x86)\Hearthstone\Logs"
    pattern = os.path.join(base_dir, "Hearthstone_*", "Power.log")
    logs = glob.glob(pattern)
    if not logs:
        return None
    return max(logs, key=os.path.getmtime)


def parse_power_log(log_path):
    """実ログ仕様に合わせてターン・リロール別の酒場提示・購入・所持金・恵み・終了時盤面/手札を抽出する"""
    games = []
    current_game = None
    entities = {}
    my_pid = None
    bob_pid = None
    my_name = None
    my_hero_eid = None
    is_recruit_phase = False
    current_turn = 0
    active_entity_id = None

    # 所持金追跡用の状態変数
    resources = 0
    resources_used = 0
    temp_resources = 0
    in_reroll_block = False

    # リロール・凍結追跡用の状態変数
    active_tavern_eids = {}  # 現在酒場(PLAY)に並んでいる {eid: card_id}
    frozen_from_prev_turn = []  # 前ターン終了時に凍結していた card_id リスト
    need_new_roll = False    # カードが流された直後かどうかのフラグ

    # 悪夢の恵み（発見）選択肢追跡用
    pending_choices = {}
    current_choice = None
    current_chosen_id = None

    # 対戦相手・戦闘・リーダーボード追跡用
    in_my_player_block = False
    next_opp_pid = None
    prev_lb_tiers_end = {}
    combat_snap_done = False
    opp_combat_hero_eid = None
    combat_hero_attacker = None  # "ME" | "OPP" | None
    combat_dmg = 0
    combat_opp_board_snap = []
    combat_opp_hero_snap = None
    combat_my_hp_before = None

    re_player = re.compile(r"Player EntityID=(\d+) PlayerID=(\d+) GameAccountId=\[hi=\d+ lo=(\d+)\]")
    re_player_name = re.compile(r"PlayerID=(\d+), PlayerName=(.+)")
    re_game_type = re.compile(r"^GameType=(\S+)")
    re_full_entity = re.compile(r"FULL_ENTITY - (?:Creating|Updating).*?(?:ID=|id=)(\d+).*?CardID=([^\s\]]*)")
    re_show_entity = re.compile(r"SHOW_ENTITY - Updating Entity=(?:\[.*?id=(\d+).*?\]|(\d+))\s+CardID=([^\s\]]*)")
    re_change_entity = re.compile(r"CHANGE_ENTITY - Updating Entity=(?:\[.*?id=(\d+).*?\]|(\d+))\s+CardID=([^\s\]]*)")
    re_tag_change = re.compile(r"TAG_CHANGE Entity=(?:\[.*?id=(\d+).*?\]|(\S+))\s+tag=(\S+)\s+value=(\S+)")
    re_sub_tag = re.compile(r"^tag=(\S+)\s+value=(\S+)")
    re_choice_id = re.compile(r"id=(\d+)")
    re_ref_card_id = re.compile(r"cardId=([^\s\]]*)")
    re_entity_name = re.compile(r"\[entityName=(.+?) id=(\d+) ")
    re_attack_block = re.compile(r"BLOCK_START BlockType=ATTACK Entity=\[.*?id=(\d+).*?\]")

    def current_gold():
        return max(0, resources + temp_resources - resources_used)

    def current_max_gold():
        return max(resources + temp_resources, current_gold())

    def get_entity(eid):
        if eid not in entities:
            entities[eid] = {
                "id": eid,
                "card_id": "",
                "name": "",
                "zone": "",
                "controller": "",
                "card_type": "",
                "atk": 0,
                "health": 0,
                "damage": 0,
                "armor": 0,
                "cost": None,
                "zone_pos": 0,
                "frozen": 0,
                "premium": 0,
                "taunt": 0,
                "divine_shield": 0,
                "reborn": 0,
                "poisonous": 0,
                "venomous": 0,
                "windfury": 0,
                "player_id": "",
                "tech_level": 1,
                "place": 0,
                "triples": 0,
                "trinket1": 0,
                "trinket2": 0,
                "transient": 0,
                "attached": "",
                "dark_gifts": [],
                "card_history": [],
                "locked_hero": 0,
                "is_pool_minion": 0,
                "entered_play": False,
                "subsets": set(),
                "was_in_tavern": False,
                "offered_recorded": False,
                "bought_recorded": False,
            }
        return entities[eid]

    def record_card_id(ent, card_id):
        if not card_id:
            return
        ent["card_id"] = card_id
        if not ent["card_history"] or ent["card_history"][-1] != card_id:
            ent["card_history"].append(card_id)

    def add_dark_gift(ent, dg_cid):
        norm = normalize_dark_gift_id(dg_cid)
        if norm and norm not in ent["dark_gifts"]:
            ent["dark_gifts"].append(norm)

    def apply_entity_tag(ent, tag, value):
        if tag == "ZONE":
            ent["zone"] = value
            if value == "PLAY":
                ent["entered_play"] = True
        elif tag == "CONTROLLER":
            ent["controller"] = value
        elif tag == "CARDTYPE":
            ent["card_type"] = value
        elif tag == "ATK":
            ent["atk"] = int(value)
        elif tag == "HEALTH":
            ent["health"] = int(value)
        elif tag == "DAMAGE":
            ent["damage"] = int(value)
        elif tag == "ARMOR":
            ent["armor"] = int(value)
        elif tag == "COST":
            ent["cost"] = int(value)
        elif tag == "ZONE_POSITION":
            ent["zone_pos"] = int(value)
        elif tag == "FROZEN":
            ent["frozen"] = int(value)
        elif tag == "PREMIUM":
            ent["premium"] = int(value)
        elif tag == "TAUNT":
            ent["taunt"] = int(value)
        elif tag == "DIVINE_SHIELD":
            ent["divine_shield"] = int(value)
        elif tag == "REBORN":
            ent["reborn"] = int(value)
        elif tag == "POISONOUS":
            ent["poisonous"] = int(value)
        elif tag == "VENOMOUS":
            ent["venomous"] = int(value)
        elif tag == "WINDFURY":
            ent["windfury"] = int(value)
        elif tag == "PLAYER_ID":
            ent["player_id"] = value
        elif tag == "PLAYER_TECH_LEVEL":
            ent["tech_level"] = int(value)
        elif tag == "PLAYER_LEADERBOARD_PLACE":
            ent["place"] = int(value)
        elif tag == "PLAYER_TRIPLES":
            ent["triples"] = int(value)
        elif tag == "BACON_FIRST_TRINKET_DATABASE_ID":
            ent["trinket1"] = int(value)
        elif tag == "BACON_SECOND_TRINKET_DATABASE_ID":
            ent["trinket2"] = int(value)
        elif tag == "TRANSIENT_ENTITY":
            ent["transient"] = int(value)
        elif tag == "BACON_LOCKED_MULLIGAN_HERO":
            ent["locked_hero"] = int(value)
        elif tag == "IS_BACON_POOL_MINION":
            ent["is_pool_minion"] = int(value)
        elif tag.startswith("BACON_SUBSET_"):
            sub = tag[len("BACON_SUBSET_"):]
            if value == "1":
                ent["subsets"].add(sub)
        elif tag == "ATTACHED":
            ent["attached"] = value
            if value and value != "0" and ent["card_id"]:
                dg = normalize_dark_gift_id(ent["card_id"])
                if dg:
                    add_dark_gift(get_entity(value), dg)
        elif tag == "DARK_GIFT_ENTITY":
            if value and value != "0":
                dg_ent = entities.get(value)
                if dg_ent and dg_ent["card_id"]:
                    add_dark_gift(ent, dg_ent["card_id"])
        elif tag == "COPIED_FROM_ENTITY_ID":
            if value and value != "0":
                src = entities.get(value)
                if src:
                    for dg in src["dark_gifts"]:
                        add_dark_gift(ent, dg)

    def collect_dark_gifts_for_entity(ent):
        """エンティティ自身の継承済み恵み + 現在PLAY中で付与されている恵みエンチャントを集約する"""
        gifts = list(ent["dark_gifts"])
        target_eid = ent["id"]
        for other in entities.values():
            if other["attached"] == target_eid and other["zone"] == "PLAY":
                dg = normalize_dark_gift_id(other["card_id"])
                if dg and dg not in gifts:
                    gifts.append(dg)
        return gifts

    def get_turn_data(turn):
        return current_game["turns"].setdefault(
            turn,
            {
                "rolls": [],
                "dark_gifts": [],
                "tier_start": 1,
                "tier_end": 1,
                "upgrade_cost_start": None,
                "gold_start": None,
                "max_gold_start": None,
                "gold_end": None,
                "max_gold_end": None,
                "board_end": [],
                "hand_end": [],
                "opp_pid": None,
                "lb_tiers_start": {},
                "leaderboard": [],
                "my_hp_start": None,
                "my_hp_end_recruit": None,
                "combat": None,
                "end_recorded": False,
            },
        )

    def get_active_leaderboard_heroes():
        """ロビー全員（自分＋敵7人）の最新ヒーローエンティティ一覧を {pid: ent} で返す"""
        by_pid = {}
        for e in entities.values():
            if (
                e["zone"] == "SETASIDE"
                and e["card_type"] == "HERO"
                and e["controller"] == bob_pid
                and e["player_id"]
                and e["player_id"] != my_pid
                and e["place"] > 0
                and not e["transient"]
                and e["card_id"]
            ):
                prev = by_pid.get(e["player_id"])
                if prev is None or int(e["id"]) > int(prev["id"]):
                    by_pid[e["player_id"]] = e
        if my_hero_eid and my_hero_eid in entities and my_pid:
            mh = entities[my_hero_eid]
            if mh["card_id"]:
                by_pid[my_pid] = mh
        return by_pid

    def build_minion_snapshot(ent):
        return {
            "card_id": ent["card_id"],
            "atk": ent["atk"],
            "health": ent["health"],
            "golden": bool(ent["premium"] or ent["card_id"].endswith("_G")),
            "taunt": bool(ent["taunt"]),
            "divine_shield": bool(ent["divine_shield"]),
            "reborn": bool(ent["reborn"]),
            "poisonous": bool(ent["poisonous"]),
            "venomous": bool(ent["venomous"]),
            "windfury": bool(ent["windfury"]),
            "dark_gifts": collect_dark_gifts_for_entity(ent),
        }

    def snapshot_combat_start():
        """戦闘開始時点の相手盤面・相手ヒーローをスナップショットする"""
        nonlocal combat_snap_done, opp_combat_hero_eid, combat_opp_board_snap, combat_opp_hero_snap
        opp_heroes = [
            e
            for e in entities.values()
            if e["controller"] == bob_pid
            and e["zone"] == "PLAY"
            and e["card_type"] == "HERO"
            and e["card_id"]
            and e["card_id"] != "TB_BaconShopBob"
        ]
        opp_board_ents = [
            e
            for e in entities.values()
            if e["controller"] == bob_pid
            and e["zone"] == "PLAY"
            and e["card_type"] == "MINION"
            and e["card_id"]
        ]
        opp_board_ents.sort(key=lambda e: e["zone_pos"])
        opp_combat_hero_eid = opp_heroes[0]["id"] if opp_heroes else None
        combat_opp_board_snap = [build_minion_snapshot(e) for e in opp_board_ents]
        if opp_heroes:
            oh = opp_heroes[0]
            combat_opp_hero_snap = {
                "card_id": oh["card_id"],
                "name": oh["name"],
                "hp": oh["health"] - oh["damage"],
                "armor": oh["armor"],
            }
        else:
            combat_opp_hero_snap = None
        combat_snap_done = True

    def finalize_combat_result():
        """戦闘終了時に勝敗・ダメージ・自残りライフ・相手盤面をターンへ記録する"""
        if not current_game or current_turn <= 0:
            return
        turn_data = get_turn_data(current_turn)
        if turn_data["combat"] is not None:
            return
        mh = entities.get(my_hero_eid) if my_hero_eid else None
        my_hp_after = (mh["health"] - mh["damage"], mh["armor"]) if mh else None

        # 対戦相手のリーダーボード情報を紐づけ
        opp_pid = turn_data["opp_pid"] or next_opp_pid
        opp_lb = None
        for entry in turn_data["leaderboard"]:
            if not entry["is_me"] and opp_pid and entry["pid"] == opp_pid:
                opp_lb = entry
                break
        if opp_lb is None and combat_opp_hero_snap:
            for entry in turn_data["leaderboard"]:
                if not entry["is_me"] and entry["card_id"] == combat_opp_hero_snap["card_id"]:
                    opp_lb = entry
                    break

        if combat_hero_attacker == "ME":
            result = "WIN"
        elif combat_hero_attacker == "OPP":
            result = "LOSS"
        else:
            result = "TIE"

        turn_data["combat"] = {
            "result": result,
            "damage": combat_dmg,
            "my_hp_before": combat_my_hp_before or turn_data["my_hp_end_recruit"],
            "my_hp_after": my_hp_after,
            "opp_board": list(combat_opp_board_snap),
            "opp_hero": opp_lb or combat_opp_hero_snap,
        }

    def create_roll(turn_data, carried_over):
        g = current_gold()
        mg = current_max_gold()
        if not turn_data["rolls"] and turn_data["gold_start"] is None:
            turn_data["gold_start"] = g
            turn_data["max_gold_start"] = mg
        roll = {
            "roll_index": len(turn_data["rolls"]),
            "offered": [],
            "carried_over": list(carried_over),
            "bought": [],
            "gold_start": g,
            "max_gold_start": mg,
            "gold_end": g,
            "max_gold_end": mg,
        }
        turn_data["rolls"].append(roll)
        return roll

    def ensure_current_roll():
        """現在のターンの最新リロール枠を取得（なければ作成）"""
        turn_data = get_turn_data(current_turn)
        if not turn_data["rolls"]:
            create_roll(turn_data, [])
        return turn_data["rolls"][-1]

    def update_current_roll_gold():
        """現在のロールの行動後所持金を更新する"""
        if not current_game or not is_recruit_phase or current_turn <= 0 or in_reroll_block:
            return
        turn_data = current_game["turns"].get(current_turn)
        if not turn_data or not turn_data["rolls"]:
            return
        roll = turn_data["rolls"][-1]
        roll["gold_end"] = current_gold()
        roll["max_gold_end"] = current_max_gold()

    def snapshot_end_of_turn():
        """ターン終了時点の自分の盤面ミニオン・手札・残り所持金・リーダーボードを記録する"""
        nonlocal frozen_from_prev_turn, prev_lb_tiers_end
        if not current_game or current_turn <= 0:
            return
        turn_data = get_turn_data(current_turn)
        if turn_data["end_recorded"]:
            return

        # 盤面ミニオン（左から順）
        board_ents = [
            e
            for e in entities.values()
            if e["controller"] == my_pid
            and e["zone"] == "PLAY"
            and e["card_type"] == "MINION"
            and e["card_id"]
        ]
        board_ents.sort(key=lambda e: e["zone_pos"])
        turn_data["board_end"] = [build_minion_snapshot(e) for e in board_ents]

        # 手札カード（左から順）
        hand_ents = [
            e
            for e in entities.values()
            if e["controller"] == my_pid and e["zone"] == "HAND" and e["card_id"]
        ]
        hand_ents.sort(key=lambda e: e["zone_pos"])
        turn_data["hand_end"] = [
            {
                "card_id": e["card_id"],
                "card_type": e["card_type"],
                "atk": e["atk"],
                "health": e["health"],
                "golden": bool(e["premium"] or e["card_id"].endswith("_G")),
                "dark_gifts": collect_dark_gifts_for_entity(e),
            }
            for e in hand_ents
        ]

        turn_data["gold_end"] = current_gold()
        turn_data["max_gold_end"] = current_max_gold()
        if turn_data["rolls"]:
            turn_data["rolls"][-1]["gold_end"] = turn_data["gold_end"]
            turn_data["rolls"][-1]["max_gold_end"] = turn_data["max_gold_end"]

        # 自分の残りライフ（雇用フェーズ終了時）
        if my_hero_eid and my_hero_eid in entities:
            mh = entities[my_hero_eid]
            turn_data["my_hp_end_recruit"] = (mh["health"] - mh["damage"], mh["armor"])

        # リーダーボード全員分（自分＋敵7人）のスナップショット
        opp_pid = next_opp_pid or turn_data["opp_pid"]
        turn_data["opp_pid"] = opp_pid
        lb_map = get_active_leaderboard_heroes()
        lb_entries = []
        new_prev_tiers = {}
        for pid, ent in lb_map.items():
            is_me = pid == my_pid
            t_end = turn_data["tier_end"] if is_me else ent["tech_level"]
            t_start = (
                turn_data["tier_start"]
                if is_me
                else turn_data["lb_tiers_start"].get(pid, prev_lb_tiers_end.get(pid, t_end))
            )
            new_prev_tiers[pid] = t_end
            lb_entries.append(
                {
                    "pid": pid,
                    "is_me": is_me,
                    "is_opponent": (not is_me) and (pid == opp_pid),
                    "card_id": ent["card_id"],
                    "name": ent["name"],
                    "place": ent["place"],
                    "tier_start": t_start,
                    "tier_end": t_end,
                    "hp": ent["health"] - ent["damage"],
                    "armor": ent["armor"],
                    "triples": ent["triples"],
                    "trinket1": ent["trinket1"],
                    "trinket2": ent["trinket2"],
                }
            )
        lb_entries.sort(key=lambda x: (x["place"] if x["place"] > 0 else 99, x["pid"]))
        turn_data["leaderboard"] = lb_entries
        if new_prev_tiers:
            prev_lb_tiers_end = new_prev_tiers

        # 凍結して次ターンに持ち越す酒場カードを記録
        frozen_from_prev_turn = [
            cid
            for eid, cid in active_tavern_eids.items()
            if eid in entities and entities[eid]["frozen"]
        ]
        active_tavern_eids.clear()
        turn_data["end_recorded"] = True

    def finalize_game_meta():
        """試合内で出現した単一種族プールミニオンから出現種族・BAN種族を確定する"""
        if not current_game:
            return
        active_set = set()
        for ent in entities.values():
            if ent["is_pool_minion"] == 1 and ent["entered_play"] and len(ent["subsets"]) == 1:
                sub = next(iter(ent["subsets"]))
                if sub in BG_TRIBE_LABELS:
                    active_set.add(sub)
        roster = list(BG_BASE_TRIBES)
        for extra in sorted(active_set):
            if extra not in roster:
                roster.append(extra)
        current_game["active_tribes"] = [t for t in roster if t in active_set]
        current_game["banned_tribes"] = [t for t in roster if t not in active_set]

    def evaluate_entity(eid):
        """エンティティの状態変化から『新規提示』『リロール発生』『購入』を判定する"""
        nonlocal need_new_roll, in_reroll_block

        # 雇用フェーズ以外はスキップ
        if not current_game or not is_recruit_phase or current_turn <= 0:
            return
        ent = entities.get(eid)
        if not ent or not ent["card_id"]:
            return

        # 1. 酒場に新しく並んだカード（ボブ所有 & PLAY & ミニオン/酒場呪文）
        if (
            ent["controller"] == bob_pid
            and ent["zone"] == "PLAY"
            and ent["card_type"] in ("MINION", "BATTLEGROUND_SPELL")
            and not ent["offered_recorded"]
        ):
            if need_new_roll:
                need_new_roll = False
                in_reroll_block = False
                turn_data = get_turn_data(current_turn)
                create_roll(turn_data, active_tavern_eids.values())

            current_roll = ensure_current_roll()
            # 初期提示時に前ターンから凍結継続したカードと一致すれば carried_over へ振り分け
            if current_roll["roll_index"] == 0 and ent["card_id"] in frozen_from_prev_turn:
                frozen_from_prev_turn.remove(ent["card_id"])
                current_roll["carried_over"].append(ent["card_id"])
            else:
                current_roll["offered"].append(ent["card_id"])

            ent["offered_recorded"] = True
            ent["was_in_tavern"] = True
            active_tavern_eids[eid] = ent["card_id"]
            return

        # 2. 酒場から購入したカード（以前酒場に存在し、自分所有 & HANDへ移動）
        if (
            ent["was_in_tavern"]
            and ent["controller"] == my_pid
            and ent["zone"] == "HAND"
            and not ent["bought_recorded"]
        ):
            active_tavern_eids.pop(eid, None)
            current_roll = ensure_current_roll()
            current_roll["bought"].append(ent["card_id"])
            ent["bought_recorded"] = True
            return

        # 3. リロール等で酒場から流されたカード（ボブ所有のままPLAY以外へ移動）
        if (
            eid in active_tavern_eids
            and ent["controller"] == bob_pid
            and ent["zone"] in ("REMOVEDFROMGAME", "GRAVEYARD", "SETASIDE")
        ):
            active_tavern_eids.pop(eid, None)
            need_new_roll = True

    with open(log_path, encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            # ゲーム種別・プレイヤー名の取得（DebugPrintGame行）
            if "GameState.DebugPrintGame() - " in raw_line and current_game:
                g_line = raw_line.split("GameState.DebugPrintGame() - ", 1)[1].strip()
                m_gtype = re_game_type.match(g_line)
                if m_gtype:
                    gtype = m_gtype.group(1)
                    current_game["game_type"] = gtype
                    current_game["is_battlegrounds"] = gtype.startswith("GT_BATTLEGROUNDS")
                    continue
                if current_game["is_battlegrounds"] is False:
                    continue
                m_pname = re_player_name.match(g_line)
                if m_pname and m_pname.group(1) == my_pid:
                    my_name = m_pname.group(2).strip()
                continue

            # 選択肢提示（開始時ヒーロー選択 & 悪夢の恵み発見）
            if "GameState.DebugPrintEntityChoices() - " in raw_line and current_game:
                if current_game["is_battlegrounds"] is False:
                    continue
                c_line = raw_line.split("GameState.DebugPrintEntityChoices() - ", 1)[1]
                if c_line.startswith("id="):
                    m_cid = re_choice_id.search(c_line)
                    choice_id = m_cid.group(1) if m_cid else ""
                    m_ctype = re.search(r"ChoiceType=(\S+)", c_line)
                    choice_type = m_ctype.group(1) if m_ctype else ""
                    turn_data = get_turn_data(current_turn) if current_turn > 0 else None
                    roll_idx = (
                        turn_data["rolls"][-1]["roll_index"]
                        if turn_data and turn_data["rolls"]
                        else 0
                    )
                    current_choice = {
                        "id": choice_id,
                        "choice_type": choice_type,
                        "source_cid": "",
                        "turn": current_turn,
                        "roll_index": roll_idx,
                        "gold": current_gold(),
                        "max_gold": current_max_gold(),
                        "options": [],
                        "chosen_eid": None,
                    }
                    if choice_id:
                        pending_choices[choice_id] = current_choice
                elif current_choice and "Source=" in c_line:
                    m_scid = re_ref_card_id.search(c_line)
                    if m_scid:
                        current_choice["source_cid"] = m_scid.group(1)
                elif current_choice and "Entities[" in c_line:
                    m_eid = re_choice_id.search(c_line)
                    m_rcid = re_ref_card_id.search(c_line)
                    if m_eid:
                        opt_eid = m_eid.group(1)
                        opt_ent = get_entity(opt_eid)
                        opt_cid = m_rcid.group(1) if m_rcid else opt_ent["card_id"]
                        if opt_cid and not opt_ent["card_history"]:
                            record_card_id(opt_ent, opt_cid)
                        dg_list = collect_dark_gifts_for_entity(opt_ent)
                        current_choice["options"].append(
                            {
                                "eid": opt_eid,
                                "card_id": opt_cid,
                                "golden": bool(opt_ent["premium"] or opt_cid.endswith("_G")),
                                "dark_gifts": dg_list,
                            }
                        )
                continue

            # 選択結果（開始時ヒーロー選択 & 悪夢の恵み発見）
            if "GameState.DebugPrintEntitiesChosen() - " in raw_line and current_game:
                if current_game["is_battlegrounds"] is False:
                    continue
                ch_line = raw_line.split("GameState.DebugPrintEntitiesChosen() - ", 1)[1]
                if ch_line.startswith("id="):
                    m_cid = re_choice_id.search(ch_line)
                    current_chosen_id = m_cid.group(1) if m_cid else None
                elif "Entities[" in ch_line and current_chosen_id in pending_choices:
                    m_eid = re_choice_id.search(ch_line)
                    cb = pending_choices[current_chosen_id]
                    if m_eid and cb["choice_type"] == "MULLIGAN" and not current_game["hero_choices"]:
                        chosen_eid = m_eid.group(1)
                        hero_opts = []
                        for opt in cb["options"]:
                            oe = get_entity(opt["eid"])
                            hist = list(oe["card_history"]) if oe["card_history"] else [opt["card_id"]]
                            hero_opts.append(
                                {
                                    "eid": opt["eid"],
                                    "history": hist,
                                    "final_card_id": hist[-1],
                                    "locked": bool(oe["locked_hero"]),
                                    "chosen": opt["eid"] == chosen_eid,
                                }
                            )
                        current_game["hero_choices"] = hero_opts
                        pending_choices.pop(current_chosen_id, None)
                    elif m_eid and cb["source_cid"] == "BG36_MidGameEffect_010" and cb["turn"] > 0:
                        cb["chosen_eid"] = m_eid.group(1)
                        get_turn_data(cb["turn"])["dark_gifts"].append(cb)
                        pending_choices.pop(current_chosen_id, None)
                continue

            if "GameState.DebugPrintPower() - " not in raw_line:
                continue
            line = raw_line.split("GameState.DebugPrintPower() - ", 1)[1].strip()

            if line.startswith("CREATE_GAME"):
                if current_game and current_game["is_battlegrounds"] is not False:
                    if is_recruit_phase and current_turn > 0:
                        snapshot_end_of_turn()
                    finalize_game_meta()
                current_game = {
                    "turns": {},
                    "hero_card_id": "",
                    "hero_choices": [],
                    "active_tribes": [],
                    "banned_tribes": [],
                    "final_place": None,
                    "game_completed": False,
                    "playstate": "",
                    "game_type": "",
                    "is_battlegrounds": None,
                    "has_bg_marker": False,
                }
                games.append(current_game)
                entities = {}
                my_pid = None
                bob_pid = None
                my_name = None
                my_hero_eid = None
                is_recruit_phase = False
                current_turn = 0
                active_entity_id = None
                resources = 0
                resources_used = 0
                temp_resources = 0
                in_reroll_block = False
                active_tavern_eids = {}
                frozen_from_prev_turn = []
                need_new_roll = False
                pending_choices = {}
                current_choice = None
                current_chosen_id = None
                in_my_player_block = False
                next_opp_pid = None
                prev_lb_tiers_end = {}
                combat_snap_done = False
                opp_combat_hero_eid = None
                combat_hero_attacker = None
                combat_dmg = 0
                combat_opp_board_snap = []
                combat_opp_hero_snap = None
                combat_my_hp_before = None
                continue

            if not current_game or current_game["is_battlegrounds"] is False:
                continue

            # エンティティの日本語名（ヒーロー名など）を自動記録
            if "[entityName=" in line:
                for m_en in re_entity_name.finditer(line):
                    e_name, e_id = m_en.groups()
                    if e_name:
                        get_entity(e_id)["name"] = e_name

            # GameType行が欠落した部分ログ用のバトルグラウンド判定フォールバック
            if not current_game["has_bg_marker"] and (
                "CardID=TB_BaconShopBob" in line
                or "CardID=TB_BaconShop_8P_PlayerE" in line
                or "tag=BACON_BARTENDER_CARD_ID " in line
                or "tag=TECH_LEVEL_MANA_GEM " in line
            ):
                current_game["has_bg_marker"] = True

            # リロールボタン押下の検知（前ロールの行動後所持金をリロール費用控除前で確定させる）
            if (
                is_recruit_phase
                and "BLOCK_START BlockType=PLAY" in line
                and "cardId=TB_BaconShop_8p_Reroll_Button" in line
            ):
                update_current_roll_gold()
                in_reroll_block = True
                continue

            # 戦闘中の攻撃ブロック検知（初回攻撃前の相手盤面スナップショット & ヒーロー攻撃による勝敗判定）
            if (not is_recruit_phase) and current_turn > 0 and "BLOCK_START BlockType=ATTACK" in line:
                if not combat_snap_done:
                    snapshot_combat_start()
                m_atk = re_attack_block.search(line)
                if m_atk:
                    atk_eid = m_atk.group(1)
                    if my_hero_eid and atk_eid == my_hero_eid:
                        combat_hero_attacker = "ME"
                    elif opp_combat_hero_eid and atk_eid == opp_combat_hero_eid:
                        combat_hero_attacker = "OPP"
                continue

            m_player = re_player.search(line)
            if m_player:
                active_entity_id = None
                _, pid, lo = m_player.groups()
                if lo != "0":
                    my_pid = pid
                    in_my_player_block = True
                else:
                    bob_pid = pid
                    in_my_player_block = False
                continue

            m_full = re_full_entity.search(line)
            if m_full:
                in_my_player_block = False
                eid, card_id = m_full.groups()
                active_entity_id = eid
                ent = get_entity(eid)
                if card_id:
                    record_card_id(ent, card_id)
                continue

            m_show = re_show_entity.search(line)
            if m_show:
                in_my_player_block = False
                eid = m_show.group(1) or m_show.group(2)
                card_id = m_show.group(3)
                active_entity_id = eid
                ent = get_entity(eid)
                if card_id:
                    record_card_id(ent, card_id)
                    if ent["attached"] and ent["attached"] != "0":
                        dg = normalize_dark_gift_id(card_id)
                        if dg:
                            add_dark_gift(get_entity(ent["attached"]), dg)
                    evaluate_entity(eid)
                continue

            m_change = re_change_entity.search(line)
            if m_change:
                in_my_player_block = False
                eid = m_change.group(1) or m_change.group(2)
                card_id = m_change.group(3)
                active_entity_id = eid
                ent = get_entity(eid)
                if card_id:
                    record_card_id(ent, card_id)
                continue

            m_tc = re_tag_change.search(line)
            if m_tc:
                in_my_player_block = False
                active_entity_id = None
                eid, entity_name, tag, value = m_tc.groups()
                if not eid and entity_name and entity_name.isdigit():
                    eid = entity_name

                # 戦闘中のヒーロー攻撃ダメージ（PREDAMAGE）を正確に記録
                if (not is_recruit_phase) and current_turn > 0 and tag == "PREDAMAGE":
                    dmg_val = int(value)
                    if dmg_val > 0:
                        if combat_hero_attacker == "ME" and eid == opp_combat_hero_eid:
                            combat_dmg = dmg_val
                        elif combat_hero_attacker == "OPP" and eid == my_hero_eid:
                            combat_dmg = dmg_val

                # ゲーム終了時のスナップショット（雇用フェーズ中に降参した場合など）
                if entity_name == "GameEntity" and tag == "STATE" and value == "COMPLETE":
                    if is_recruit_phase and current_turn > 0:
                        snapshot_end_of_turn()
                    elif (not is_recruit_phase) and current_turn > 0:
                        finalize_combat_result()
                    current_game["game_completed"] = True
                    is_recruit_phase = False
                    continue

                # 戦闘フェーズの盤面スナップショット & 終了処理
                if entity_name == "GameEntity" and tag == "STEP" and (not is_recruit_phase) and current_turn > 0:
                    if value in ("MAIN_START", "MAIN_ACTION") and not combat_snap_done:
                        snapshot_combat_start()
                        if not opp_combat_hero_eid and value == "MAIN_START":
                            combat_snap_done = False
                    elif value == "MAIN_END":
                        if not combat_snap_done:
                            snapshot_combat_start()
                        finalize_combat_result()
                    continue

                # 雇用フェーズのアクション開始時点でロール枠・昇格コスト・ロビー開始グレードを確定
                if entity_name == "GameEntity" and tag == "STEP" and value == "MAIN_ACTION":
                    if is_recruit_phase and current_turn > 0:
                        turn_data = get_turn_data(current_turn)
                        if next_opp_pid:
                            turn_data["opp_pid"] = next_opp_pid
                        for pid, lb_ent in get_active_leaderboard_heroes().items():
                            turn_data["lb_tiers_start"].setdefault(pid, lb_ent["tech_level"])
                        if turn_data["my_hp_start"] is None and my_hero_eid and my_hero_eid in entities:
                            mh = entities[my_hero_eid]
                            turn_data["my_hp_start"] = (mh["health"] - mh["damage"], mh["armor"])
                        if turn_data["upgrade_cost_start"] is None:
                            for e in entities.values():
                                if (
                                    e["controller"] == my_pid
                                    and e["zone"] == "PLAY"
                                    and e["card_id"].startswith("TB_BaconShopTechUp")
                                    and e["card_id"].endswith("_Button")
                                    and e["cost"] is not None
                                ):
                                    turn_data["upgrade_cost_start"] = e["cost"]
                                    break
                        if not turn_data["rolls"] and (active_tavern_eids or frozen_from_prev_turn):
                            create_roll(turn_data, frozen_from_prev_turn)
                            frozen_from_prev_turn = []
                    continue

                # 自分のプレイヤー状態（雇用フェーズ切替・実ターン番号・所持金・グレード・ヒーロー・対戦相手）
                if my_name and entity_name == my_name:
                    if tag == "CURRENT_PLAYER":
                        if value == "1":
                            is_recruit_phase = True
                            need_new_roll = False
                            in_reroll_block = False
                            temp_resources = 0
                        else:
                            if is_recruit_phase and current_turn > 0:
                                snapshot_end_of_turn()
                            is_recruit_phase = False
                            in_reroll_block = False
                            combat_snap_done = False
                            opp_combat_hero_eid = None
                            combat_hero_attacker = None
                            combat_dmg = 0
                            combat_opp_board_snap = []
                            combat_opp_hero_snap = None
                            mh = entities.get(my_hero_eid) if my_hero_eid else None
                            combat_my_hp_before = (mh["health"] - mh["damage"], mh["armor"]) if mh else None
                    elif tag == "TURN" and is_recruit_phase:
                        current_turn = int(value)
                        if current_turn > 0:
                            turn_data = get_turn_data(current_turn)
                            if prev_lb_tiers_end:
                                turn_data["lb_tiers_start"] = dict(prev_lb_tiers_end)
                            if next_opp_pid:
                                turn_data["opp_pid"] = next_opp_pid
                            if current_turn - 1 in current_game["turns"]:
                                prev_tier = current_game["turns"][current_turn - 1]["tier_end"]
                                turn_data["tier_start"] = prev_tier
                                turn_data["tier_end"] = prev_tier
                    elif tag == "NEXT_OPPONENT_PLAYER_ID":
                        next_opp_pid = value
                        if is_recruit_phase and current_turn > 0:
                            get_turn_data(current_turn)["opp_pid"] = value
                    elif tag == "HERO_ENTITY":
                        my_hero_eid = value
                        hero_ent = entities.get(value)
                        if hero_ent and hero_ent["card_id"]:
                            current_game["hero_card_id"] = hero_ent["card_id"]
                    elif tag == "PLAYSTATE" and value in ("WON", "LOST"):
                        current_game["playstate"] = value
                        current_game["game_completed"] = True
                        if value == "WON":
                            current_game["final_place"] = 1
                    elif tag == "PLAYER_TECH_LEVEL" and is_recruit_phase and current_turn > 0:
                        get_turn_data(current_turn)["tier_end"] = int(value)
                    elif tag == "RESOURCES":
                        resources = int(value)
                        if is_recruit_phase and current_turn > 0:
                            turn_data = get_turn_data(current_turn)
                            if not turn_data["rolls"]:
                                turn_data["gold_start"] = current_gold()
                                turn_data["max_gold_start"] = current_max_gold()
                            update_current_roll_gold()
                    elif tag == "RESOURCES_USED":
                        resources_used = int(value)
                        if is_recruit_phase and current_turn > 0:
                            turn_data = get_turn_data(current_turn)
                            if not turn_data["rolls"]:
                                turn_data["gold_start"] = current_gold()
                                turn_data["max_gold_start"] = current_max_gold()
                            update_current_roll_gold()
                    elif tag == "TEMP_RESOURCES":
                        temp_resources = int(value)
                        update_current_roll_gold()
                    continue

                # 自分のヒーローエンティティの対戦相手ID・最終順位
                if eid and my_hero_eid and eid == my_hero_eid:
                    if tag == "NEXT_OPPONENT_PLAYER_ID":
                        next_opp_pid = value
                        if is_recruit_phase and current_turn > 0:
                            get_turn_data(current_turn)["opp_pid"] = value
                    elif tag == "PLAYER_LEADERBOARD_PLACE":
                        place_val = int(value)
                        if place_val > 0 and current_game["playstate"] != "WON":
                            current_game["final_place"] = place_val

                # 酒場グレードアップの検知（自分のヒーローエンティティ）
                if eid and tag == "PLAYER_TECH_LEVEL" and is_recruit_phase and current_turn > 0:
                    ent = get_entity(eid)
                    if ent["controller"] == my_pid and ent["zone"] == "PLAY":
                        get_turn_data(current_turn)["tier_end"] = int(value)

                if eid:
                    ent = get_entity(eid)
                    apply_entity_tag(ent, tag, value)
                    evaluate_entity(eid)
                continue

            m_sub = re_sub_tag.match(line)
            if m_sub:
                tag, value = m_sub.groups()
                if in_my_player_block and tag == "NEXT_OPPONENT_PLAYER_ID":
                    next_opp_pid = value
                elif active_entity_id:
                    ent = get_entity(active_entity_id)
                    apply_entity_tag(ent, tag, value)
                    evaluate_entity(active_entity_id)

    if current_game and current_game["is_battlegrounds"] is not False:
        if is_recruit_phase and current_turn > 0:
            snapshot_end_of_turn()
        finalize_game_meta()

    bg_games = [
        g
        for g in games
        if g["turns"]
        and (
            g["is_battlegrounds"] is True
            or (g["is_battlegrounds"] is None and g["has_bg_marker"])
        )
    ]
    return bg_games


def generate_html(games, output_path, card_catalog=None, game_numbers=None):
    """リロールごとの酒場・所持金・グレード・悪夢の恵み・盤面/手札・戦闘結果・ロビー情報をHTML出力する"""
    if card_catalog is None:
        card_catalog = fetch_card_catalog()
    if game_numbers is None:
        game_numbers = list(range(1, len(games) + 1))
    dark_gift_db = card_catalog.get("dark_gifts", {})
    by_dbf_id = card_catalog.get("by_dbf_id", {})
    by_card_id = card_catalog.get("by_card_id", {})
    bgs_base = "https://art.hearthstonejson.com/v1/bgs/latest/jaJP/256x"
    render_base = "https://art.hearthstonejson.com/v1/render/latest/jaJP/256x"
    used_card_ids = set()

    def resolve_card_entry(card_id):
        if not card_id:
            return None
        info = by_card_id.get(card_id)
        if info:
            return info
        if card_id.endswith("_G"):
            return by_card_id.get(card_id[:-2])
        return None

    def resolve_card_name(card_id):
        info = resolve_card_entry(card_id)
        if info and info.get("name"):
            return info["name"]
        return card_id or ""

    def build_img_tag(card_id, css_class="", alt=None, lazy=True, is_hero=False):
        if card_id:
            used_card_ids.add(card_id)
        safe_cid = html.escape(card_id)
        card_name = resolve_card_name(card_id)
        alt_text = alt if alt is not None else (card_name or card_id)
        if card_name and card_name != card_id:
            title_text = f"{card_name} ({card_id})"
        elif alt_text and alt_text != card_id:
            title_text = f"{alt_text} ({card_id})"
        else:
            title_text = card_id
        safe_alt = html.escape(alt_text)
        safe_title = html.escape(title_text)
        primary = f"{render_base}/{safe_cid}.png" if is_hero else f"{bgs_base}/{safe_cid}.png"
        class_attr = f" class='{css_class}'" if css_class else ""
        hero_attr = " data-hero='1'" if is_hero else ""
        lazy_attr = " loading='lazy'" if lazy else ""
        return (
            f"<img{class_attr} src='{primary}' data-cid='{safe_cid}'{hero_attr} "
            f"onerror='fallbackImg(this)' alt='{safe_alt}' title='{safe_title}'{lazy_attr}>"
        )

    def render_coins(gold, max_gold=None, label=None):
        """所持金をコインSVGアイコン列（JS展開）と数値で描画する"""
        if gold is None:
            return ""
        total_slots = max(gold, max_gold if max_gold is not None else gold)
        spent = max(0, total_slots - gold)
        num_text = f"{gold}/{max_gold}" if max_gold is not None else str(gold)
        label_html = f"<span class='gold-label'>{html.escape(label)}</span>" if label else ""
        return (
            f"<span class='gold-group' title='所持金 {num_text}'>"
            f"{label_html}<span class='coin-tray' data-on='{gold}' data-off='{spent}'></span>"
            f"<span class='gold-num'>{num_text}</span>"
            f"</span>"
        )

    def render_tier_badge(tier_start, tier_end, upgrade_cost_start=None):
        """ターン開始時・終了時の酒場グレードと開始時の昇格必要コイン数を描画する"""
        upgraded = tier_end > tier_start
        cls = "tier-badge tier-up" if upgraded else "tier-badge"
        up_tag = "<span class='tier-up-tag'>UP</span>" if upgraded else ""
        if upgrade_cost_start is not None:
            cost_html = (
                f"<span class='tier-cost' title='ターン開始時の酒場グレードアップ必要コイン数'>"
                f"<span class='tier-label'>開始時UP費用</span>"
                f"<svg class='coin-icon' viewBox='0 0 24 24'><use href='#coin-on'/></svg>"
                f"<span class='gold-num'>{upgrade_cost_start}</span>"
                f"</span>"
            )
        else:
            cost_html = (
                f"<span class='tier-cost'>"
                f"<span class='tier-label'>開始時UP費用</span>"
                f"<span class='tier-max'>MAX</span>"
                f"</span>"
            )
        return (
            f"<span class='{cls}'>"
            f"<span class='tier-label'>酒場グレード</span>"
            f"<span class='tier-val'>開始 ★{tier_start} → 終了 ★{tier_end}</span>"
            f"{up_tag}"
            f"</span>"
            f"{cost_html}"
        )

    def render_dark_gift_box(dg_ids):
        """ミニオンに付与された「悪夢の恵み」効果名と説明を描画する"""
        if not dg_ids:
            return ""
        items = []
        seen = set()
        for dg_cid in dg_ids:
            name, text = dark_gift_db.get(dg_cid, (dg_cid, ""))
            if (name, text) in seen:
                continue
            seen.add((name, text))
            safe_name = html.escape(name)
            safe_text = html.escape(text)
            text_html = f"<div class='dg-desc'>{safe_text}</div>" if safe_text else ""
            items.append(
                f"<div class='dg-effect-box' title='{safe_name}: {safe_text}'>"
                f"<div class='dg-name'>✦ {safe_name}</div>"
                f"{text_html}"
                f"</div>"
            )
        return "".join(items)

    def render_place_badge(game, show_prefix=False):
        """最終順位バッジを描画する"""
        place = game.get("final_place")
        if place is None:
            return ""
        completed = game.get("game_completed", False)
        if place == 1:
            cls = "place-badge place-1st"
            icon = "👑 "
        elif place <= 4:
            cls = "place-badge place-top4"
            icon = ""
        else:
            cls = "place-badge place-bottom"
            icon = ""
        prefix = "最終順位: " if show_prefix else ""
        suffix = "" if completed else "（途中終了）"
        return f"<span class='{cls}'>{icon}{prefix}{place}位{suffix}</span>"

    def render_minion_badges(m):
        parts = []
        if m["golden"]:
            parts.append("<span class='kw-tag kw-gold'>ゴールデン</span>")
        if m["taunt"]:
            parts.append("<span class='kw-tag kw-taunt'>挑発</span>")
        if m["divine_shield"]:
            parts.append("<span class='kw-tag kw-ds'>聖盾</span>")
        if m["reborn"]:
            parts.append("<span class='kw-tag kw-reborn'>蘇り</span>")
        if m["poisonous"]:
            parts.append("<span class='kw-tag kw-poison'>猛毒</span>")
        if m["venomous"]:
            parts.append("<span class='kw-tag kw-poison'>毒袋</span>")
        if m["windfury"]:
            parts.append("<span class='kw-tag kw-wf'>疾風</span>")
        if not parts:
            return ""
        return f"<div class='kw-row'>{''.join(parts)}</div>"

    def render_minion_card(m):
        cls_list = ["card-item"]
        if m["golden"]:
            cls_list.append("golden")
        if m.get("dark_gifts"):
            cls_list.append("has-dg")
        return (
            f"<div class='{' '.join(cls_list)}'>"
            f"{build_img_tag(m['card_id'])}"
            f"<div class='stat-pill'>"
            f"<span class='stat-atk'>{m['atk']}</span>"
            f"<span class='stat-hp'>{m['health']}</span>"
            f"</div>"
            f"{render_minion_badges(m)}"
            f"{render_dark_gift_box(m.get('dark_gifts', []))}"
            f"</div>"
        )

    def resolve_hero_name(entry):
        if not entry:
            return "不明"
        if entry.get("name"):
            return entry["name"]
        cid = entry.get("card_id", "")
        if cid in by_card_id:
            return by_card_id[cid]["name"]
        return cid or "不明"

    def render_life_span(hp, armor):
        if hp is None:
            return ""
        if hp <= 0:
            return f"<span class='life-dead'>💀 {hp}</span>"
        armor_html = f"<span class='armor-num'>+{armor}</span>" if armor and armor > 0 else ""
        return f"<span class='life-hp'>♥{hp}</span>{armor_html}"

    def render_trinket_chip(dbf_id, slot_label):
        if not dbf_id:
            return ""
        info = by_dbf_id.get(int(dbf_id))
        if info:
            cid = info["id"]
            name = html.escape(info["name"])
            desc = html.escape(info["text"])
            thumb = build_img_tag(cid, css_class="trinket-thumb zoomable-img", alt=info["name"])
            return (
                f"<span class='trinket-chip' title='{html.escape(slot_label)}: {name} — {desc}'>"
                f"{thumb}<span class='trinket-slot'>{html.escape(slot_label)}</span>"
                f"<span class='trinket-name'>{name}</span>"
                f"</span>"
            )
        return (
            f"<span class='trinket-chip'>"
            f"<span class='trinket-slot'>{html.escape(slot_label)}</span>"
            f"<span class='trinket-name'>ID:{dbf_id}</span>"
            f"</span>"
        )

    is_single_game = len(games) == 1
    page_title = (
        f"バトルグラウンド振り返りログ（第{game_numbers[0]}試合）"
        if is_single_game
        else "バトルグラウンド振り返りログ（リロール別）"
    )

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='ja'>",
        "<head>",
        "<meta charset='UTF-8'>",
        f"<title>{page_title}</title>",
        "<style>",
        "  html { scroll-behavior: smooth; }",
        "  body { font-family: sans-serif; background: #1a1c23; color: #f0f0f0; padding: 0 20px 20px; margin: 0; }",
        "  h1, h2 { border-bottom: 1px solid #3a3f4b; padding-bottom: 8px; }",
        "  .sticky-nav { position: sticky; top: 0; z-index: 500; background: rgba(20, 22, 30, 0.94); backdrop-filter: blur(6px); border-bottom: 1px solid #343946; margin: 0 -20px 18px; padding: 8px 20px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }",
        "  .sticky-nav-label { font-size: 0.8em; color: #9aa3b2; margin-right: 4px; }",
        "  .nav-pill { display: inline-flex; align-items: center; gap: 5px; padding: 4px 11px; border-radius: 999px; background: #252936; border: 1px solid #3d4457; color: #e6ecf5; text-decoration: none; font-size: 0.85em; font-weight: bold; transition: background 0.12s, border-color 0.12s; }",
        "  .nav-pill:hover { background: #31384b; border-color: #6ca4f2; color: #fff; }",
        "  .nav-pill-toc { background: #2c261a; border-color: #6b5627; color: #ffd75e; }",
        "  .nav-pill-toc:hover { background: #3d3420; border-color: #ffd100; }",
        "  .toc-box { background: #222631; border: 1px solid #383e4e; border-radius: 8px; padding: 14px 16px; margin-bottom: 24px; scroll-margin-top: 60px; }",
        "  .toc-title { font-size: 1.02em; font-weight: bold; color: #ffd100; margin-bottom: 12px; }",
        "  .toc-list { display: flex; flex-direction: column; gap: 10px; }",
        "  .toc-game { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; background: #1b1e27; border: 1px solid #303545; border-radius: 6px; padding: 10px 12px; }",
        "  .toc-game-link { display: inline-flex; align-items: center; gap: 10px; text-decoration: none; color: #f0f4fa; font-weight: bold; min-width: 210px; }",
        "  .toc-game-link:hover .toc-game-name { color: #7fb8ff; text-decoration: underline; }",
        "  .toc-hero-img { width: 42px; height: 42px; object-fit: cover; border-radius: 6px; border: 1px solid #444b5e; display: block; }",
        "  .toc-game-meta { font-size: 0.78em; color: #9aa3b2; font-weight: normal; margin-top: 2px; }",
        "  .toc-turns { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }",
        "  .toc-turn-link { display: inline-flex; align-items: center; gap: 3px; padding: 3px 8px; border-radius: 5px; background: #262b38; border: 1px solid #3a4154; color: #cfd8e8; text-decoration: none; font-size: 0.78em; font-variant-numeric: tabular-nums; }",
        "  .toc-turn-link:hover { background: #333b4f; border-color: #6ca4f2; color: #fff; }",
        "  .toc-turn-dg { border-color: #7c4db8; background: #281f38; color: #e2c2ff; }",
        "  .toc-turn-dg:hover { background: #372850; border-color: #b25cff; }",
        "  .game-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; scroll-margin-top: 60px; }",
        "  .game-header h2 { flex: 1; margin: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }",
        "  .place-badge { display: inline-flex; align-items: center; font-size: 0.72em; font-weight: bold; padding: 3px 10px; border-radius: 999px; vertical-align: middle; }",
        "  .toc-game-name { display: flex; align-items: center; gap: 8px; }",
        "  .toc-game-name .place-badge { font-size: 0.78em; padding: 1px 8px; }",
        "  .place-1st { background: #3b2f0b; border: 1px solid #ffd700; color: #ffe46b; box-shadow: 0 0 8px rgba(255, 215, 0, 0.3); }",
        "  .place-top4 { background: #183325; border: 1px solid #4caf50; color: #9cf0be; }",
        "  .place-bottom { background: #301f24; border: 1px solid #8a434e; color: #f0a8b2; }",
        "  .back-to-toc { font-size: 0.82em; color: #ffd75e; text-decoration: none; padding: 4px 10px; border-radius: 999px; border: 1px solid #594a26; background: #262116; white-space: nowrap; }",
        "  .back-to-toc:hover { background: #38301e; border-color: #ffd100; }",
        "  .hero-img { width: 90px; border-radius: 6px; }",
        "  .game-info-box { background: #222631; border: 1px solid #353b4b; border-radius: 8px; padding: 14px 16px; margin-bottom: 20px; display: flex; flex-direction: column; gap: 14px; }",
        "  .game-info-section { display: flex; flex-direction: column; gap: 6px; }",
        "  .game-info-title { font-size: 0.85em; font-weight: bold; color: #b7c2d4; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }",
        "  .game-info-note { font-size: 0.82em; font-weight: normal; color: #8c96a8; }",
        "  .tribe-rows { display: flex; flex-direction: column; gap: 6px; }",
        "  .tribe-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }",
        "  .tribe-line-label { font-size: 0.78em; color: #9aa3b2; min-width: 96px; }",
        "  .tribe-chip { font-size: 0.78em; font-weight: bold; padding: 2px 9px; border-radius: 999px; }",
        "  .tribe-active { background: #1d352a; border: 1px solid #3f8f62; color: #9cf0be; }",
        "  .tribe-ban { background: #311d22; border: 1px solid #7d3642; color: #f09aa6; text-decoration: line-through; }",
        "  .hero-choices-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-start; }",
        "  .hero-choice-slot { display: inline-flex; align-items: center; gap: 6px; background: #1a1d26; border: 1px solid #323848; border-radius: 8px; padding: 8px; }",
        "  .hero-choice-slot.is-chosen { border: 2px solid #4caf50; background: #1a271f; box-shadow: 0 0 10px rgba(76, 175, 80, 0.3); }",
        "  .hero-choice-slot.is-locked { opacity: 0.58; }",
        "  .hero-choice-card { width: 96px; }",
        "  .hero-choice-card img { width: 96px; }",
        "  .hero-choice-rerolled-from { opacity: 0.65; width: 82px; }",
        "  .hero-choice-rerolled-from img { width: 82px; }",
        "  .hero-reroll-arrow { color: #7fb8ff; font-weight: bold; font-size: 1.1em; }",
        "  .badge-locked { background: #4b5263; color: #e2e7f0; }",
        "  .badge-reroll-from { background: #3b5998; color: #e8f0ff; }",
        "  .turn-box { background: #252832; border-radius: 8px; padding: 16px; margin-bottom: 24px; scroll-margin-top: 60px; }",
        "  .turn-title { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 1.2em; font-weight: bold; color: #ffd100; margin-bottom: 12px; }",
        "  .turn-meta { font-size: 0.78em; color: #a0aab8; font-weight: normal; display: inline-flex; flex-wrap: wrap; align-items: center; gap: 10px; }",
        "  .tier-badge { display: inline-flex; align-items: center; gap: 6px; background: #161920; border: 1px solid #3a4254; border-radius: 999px; padding: 2px 10px; }",
        "  .tier-up { border-color: #4caf50; background: #19261d; }",
        "  .tier-label { color: #9aa3b2; font-size: 0.85em; }",
        "  .tier-val { color: #e8edf5; font-weight: bold; font-size: 0.9em; }",
        "  .tier-up-tag { background: #4caf50; color: #fff; font-size: 0.72em; font-weight: bold; padding: 1px 5px; border-radius: 4px; }",
        "  .tier-cost { display: inline-flex; align-items: center; gap: 5px; background: #161920; border: 1px solid #4e4226; border-radius: 999px; padding: 2px 10px; }",
        "  .tier-max { color: #9aa3b2; font-weight: bold; font-size: 0.85em; }",
        "  .roll-block { background: #1e2129; border-left: 4px solid #4a90e2; border-radius: 4px; padding: 12px; margin-bottom: 12px; }",
        "  .roll-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-weight: bold; color: #7fb8ff; margin-bottom: 8px; font-size: 0.95em; }",
        "  .roll-gold-bar { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 8px; font-weight: normal; font-size: 0.85em; }",
        "  .gold-group { display: inline-flex; align-items: center; gap: 5px; background: #161920; border: 1px solid #343946; border-radius: 999px; padding: 2px 9px; }",
        "  .gold-label { color: #9aa3b2; font-size: 0.85em; }",
        "  .coin-tray { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 2px; }",
        "  .coin-icon { width: 16px; height: 16px; display: block; flex-shrink: 0; }",
        "  .gold-num { color: #ffd75e; font-weight: bold; font-size: 0.9em; font-variant-numeric: tabular-nums; }",
        "  .gold-arrow { color: #7e889b; font-weight: bold; }",
        "  .roll-content { display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start; }",
        "  .sub-group { display: flex; flex-direction: column; }",
        "  .sub-label { font-size: 0.8em; color: #9aa3b2; margin-bottom: 4px; }",
        "  .card-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start; }",
        "  .card-item { position: relative; text-align: center; width: 120px; }",
        "  .card-item img { width: 120px; border-radius: 6px; display: block; cursor: zoom-in; transition: transform 0.12s ease; }",
        "  .card-item img:hover, .hero-img:hover { transform: scale(1.05); }",
        "  .hero-img { cursor: zoom-in; transition: transform 0.12s ease; }",
        "  .card-modal { display: none; position: fixed; inset: 0; z-index: 9999; background: rgba(10, 12, 18, 0.86); backdrop-filter: blur(3px); align-items: center; justify-content: center; padding: 24px; }",
        "  .card-modal.open { display: flex; }",
        "  .card-modal-inner { position: relative; display: flex; flex-direction: column; align-items: center; max-width: 92vw; max-height: 92vh; }",
        "  .card-modal-img { width: min(380px, 82vw); max-height: 76vh; object-fit: contain; border-radius: 10px; filter: drop-shadow(0 12px 28px rgba(0,0,0,0.75)); }",
        "  .card-modal-close { position: absolute; top: -12px; right: -12px; width: 34px; height: 34px; border-radius: 50%; border: 1px solid #555e73; background: #1e222d; color: #fff; font-size: 20px; line-height: 1; cursor: pointer; display: flex; align-items: center; justify-content: center; }",
        "  .card-modal-close:hover { background: #343b4d; }",
        "  .card-modal-extra { margin-top: 10px; max-width: 380px; width: 100%; display: flex; flex-direction: column; align-items: center; gap: 6px; }",
        "  .card-modal-extra .stat-pill { font-size: 1.05em; }",
        "  .card-modal-extra .dg-effect-box { width: 100%; box-sizing: border-box; padding: 8px 12px; }",
        "  .card-modal-extra .dg-name { font-size: 0.95em; }",
        "  .card-modal-extra .dg-desc { font-size: 0.86em; }",
        "  .card-modal-hint { margin-top: 8px; font-size: 0.78em; color: #9aa3b2; }",
        "  .bought img { outline: 3px solid #4caf50; }",
        "  .frozen img { outline: 2px dashed #00bcd4; opacity: 0.9; }",
        "  .golden img { outline: 2px solid #ffd700; box-shadow: 0 0 8px rgba(255, 215, 0, 0.45); }",
        "  .badge { position: absolute; top: 4px; right: 4px; font-size: 0.65em; padding: 2px 5px; border-radius: 3px; font-weight: bold; z-index: 2; }",
        "  .badge-buy { background: #4caf50; color: #fff; }",
        "  .badge-freeze { background: #008ba3; color: #fff; }",
        "  .badge-dg-chosen { background: #b25cff; color: #fff; }",
        "  .dg-block { background: #221d2e; border-left: 4px solid #b25cff; border-radius: 4px; padding: 12px; margin-bottom: 12px; }",
        "  .dg-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-weight: bold; color: #d7a6ff; margin-bottom: 10px; font-size: 0.95em; }",
        "  .dg-option { width: 148px; background: #191623; border: 1px solid #382e4d; border-radius: 8px; padding: 8px; box-sizing: border-box; }",
        "  .dg-option img { width: 130px; margin: 0 auto; }",
        "  .dg-option-chosen { border: 2px solid #b25cff; background: #261c38; box-shadow: 0 0 12px rgba(178, 92, 255, 0.35); }",
        "  .dg-option-unchosen { opacity: 0.72; }",
        "  .dg-effect-box { margin-top: 6px; padding: 4px 6px; border-radius: 5px; background: #2b1f3d; border: 1px solid #6b469e; text-align: left; }",
        "  .dg-name { font-size: 0.73em; font-weight: bold; color: #e0b8ff; line-height: 1.3; }",
        "  .dg-desc { font-size: 0.66em; color: #d5cce6; line-height: 1.35; margin-top: 2px; }",
        "  .has-dg img { outline: 2px solid #b25cff; }",
        "  .golden.has-dg img { outline: 2px solid #ffd700; box-shadow: 0 0 10px rgba(178, 92, 255, 0.7); }",
        "  .end-turn-block { background: #20232d; border-left: 4px solid #f0b429; border-radius: 4px; padding: 12px; margin-top: 14px; }",
        "  .combat-block .end-turn-block { background: #1c1f29; border: 1px solid #353a4a; border-left: 4px solid #f0b429; margin-top: 12px; }",
        "  .end-turn-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-weight: bold; color: #f6c453; margin-bottom: 10px; font-size: 0.95em; }",
        "  .end-turn-content { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; }",
        "  .stat-pill { display: inline-flex; justify-content: center; gap: 6px; margin-top: 5px; font-size: 0.82em; font-weight: bold; }",
        "  .stat-atk { background: #c58b10; color: #fff; padding: 1px 7px; border-radius: 10px; }",
        "  .stat-hp { background: #b8292f; color: #fff; padding: 1px 7px; border-radius: 10px; }",
        "  .kw-row { display: flex; flex-wrap: wrap; justify-content: center; gap: 3px; margin-top: 4px; }",
        "  .kw-tag { font-size: 0.65em; padding: 1px 5px; border-radius: 3px; font-weight: bold; }",
        "  .kw-gold { background: #d4a017; color: #1a1c23; }",
        "  .kw-taunt { background: #5c667a; color: #fff; }",
        "  .kw-ds { background: #e8c547; color: #1a1c23; }",
        "  .kw-reborn { background: #2f89c5; color: #fff; }",
        "  .kw-poison { background: #2e8b57; color: #fff; }",
        "  .kw-wf { background: #4fa3a5; color: #fff; }",
        "  .empty-note { color: #6c7586; font-size: 0.85em; padding-top: 10px; }",
        "  .zoomable-img { cursor: zoom-in; transition: transform 0.12s ease; }",
        "  .zoomable-img:hover { transform: scale(1.08); }",
        "  .life-pill { display: inline-flex; align-items: center; gap: 5px; background: #161920; border: 1px solid #4d2a30; border-radius: 999px; padding: 2px 10px; font-size: 0.9em; }",
        "  .life-hp { color: #ff7b82; font-weight: bold; font-variant-numeric: tabular-nums; }",
        "  .armor-num { color: #8ec5ff; font-weight: bold; margin-left: 2px; font-variant-numeric: tabular-nums; }",
        "  .life-dead { color: #9c7b80; font-weight: bold; }",
        "  .vs-pill { display: inline-flex; align-items: center; gap: 6px; background: #261b20; border: 1px solid #59353f; border-radius: 999px; padding: 2px 10px; font-size: 0.88em; color: #f5d0d5; }",
        "  .vs-mini-img { width: 20px; height: 20px; border-radius: 4px; object-fit: cover; display: block; }",
        "  .combat-block { background: #241c21; border-left: 4px solid #e05263; border-radius: 4px; padding: 12px; margin-top: 14px; }",
        "  .combat-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-weight: bold; color: #ff8f9c; margin-bottom: 10px; font-size: 0.95em; }",
        "  .combat-res-badge { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: 999px; font-size: 0.88em; font-weight: bold; }",
        "  .combat-res-win { background: #1a3b28; border: 1px solid #4caf50; color: #9cf0be; }",
        "  .combat-res-loss { background: #3f1c22; border: 1px solid #e05263; color: #ffb3bc; }",
        "  .combat-res-tie { background: #262c3a; border: 1px solid #5a667d; color: #cbd5e6; }",
        "  .opp-summary-card { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; background: #1b161a; border: 1px solid #3f2d34; border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; }",
        "  .opp-hero-thumb { width: 48px; height: 48px; border-radius: 6px; object-fit: cover; display: block; border: 1px solid #5c434d; }",
        "  .opp-summary-info { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 200px; }",
        "  .opp-summary-top { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-weight: bold; color: #f5e6e8; font-size: 0.95em; }",
        "  .opp-meta-chip { font-size: 0.78em; font-weight: normal; background: #262027; border: 1px solid #423540; border-radius: 999px; padding: 1px 8px; color: #d4c6ce; }",
        "  .opp-tier-up { border-color: #4caf50; color: #9cf0be; background: #1b2d22; }",
        "  .trinket-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }",
        "  .trinket-chip { display: inline-flex; align-items: center; gap: 5px; background: #241f30; border: 1px solid #524470; border-radius: 6px; padding: 2px 7px 2px 3px; font-size: 0.78em; color: #e2d6fa; }",
        "  .trinket-thumb { width: 22px; height: 22px; border-radius: 4px; object-fit: cover; display: block; }",
        "  .trinket-slot { font-size: 0.85em; color: #a796cc; font-weight: bold; }",
        "  .trinket-name { font-weight: bold; }",
        "  .lb-details { margin-top: 12px; background: #1c1f28; border: 1px solid #333847; border-radius: 6px; padding: 8px 12px; }",
        "  .lb-details summary { cursor: pointer; font-size: 0.86em; font-weight: bold; color: #b7c4d9; user-select: none; }",
        "  .lb-details summary:hover { color: #e4ecfa; }",
        "  .lb-table-wrap { overflow-x: auto; margin-top: 8px; }",
        "  .lb-table { width: 100%; border-collapse: collapse; font-size: 0.82em; }",
        "  .lb-table th { text-align: left; color: #8f9bb0; border-bottom: 1px solid #343a4a; padding: 5px 8px; white-space: nowrap; }",
        "  .lb-table td { border-bottom: 1px solid #282d3a; padding: 5px 8px; vertical-align: middle; }",
        "  .lb-row-me { background: rgba(255, 209, 0, 0.08); }",
        "  .lb-row-opp { background: rgba(224, 82, 99, 0.12); }",
        "  .lb-row-dead { opacity: 0.55; }",
        "  .lb-hero-cell { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }",
        "  .lb-hero-img { width: 28px; height: 28px; border-radius: 5px; object-fit: cover; display: block; }",
        "  .lb-tag-me { background: #594a14; border: 1px solid #ffd100; color: #ffe573; font-size: 0.78em; padding: 0 5px; border-radius: 4px; font-weight: bold; }",
        "  .lb-tag-opp { background: #521e27; border: 1px solid #e05263; color: #ffb3bc; font-size: 0.78em; padding: 0 5px; border-radius: 4px; font-weight: bold; }",
        "</style>",
        "<script>",
        "const BGS_BASE = 'https://art.hearthstonejson.com/v1/bgs/latest/jaJP/256x';",
        "const RENDER_BASE = 'https://art.hearthstonejson.com/v1/render/latest/jaJP/256x';",
        "const ART_BASE = 'https://art.hearthstonejson.com/v1/256x';",
        "function fallbackImg(img) {",
        "  if (!img.dataset.fbInit) {",
        "    const cid = img.dataset.cid || '';",
        "    const isHero = img.dataset.hero === '1';",
        "    const cands = isHero",
        "      ? [`${BGS_BASE}/${cid}.png`, `${ART_BASE}/${cid}.jpg`]",
        "      : [",
        "          `${RENDER_BASE}/${cid}.png`,",
        "          ...(cid.endsWith('_G') ? [`${BGS_BASE}/${cid.slice(0, -2)}.png`] : []),",
        "          `${ART_BASE}/${cid}.jpg`,",
        "        ];",
        "    img.dataset.fallbacks = cands.join('|');",
        "    img.dataset.fbInit = '1';",
        "  }",
        "  const list = (img.dataset.fallbacks || '').split('|').filter(Boolean);",
        "  if (list.length > 0) {",
        "    img.src = list.shift();",
        "    img.dataset.fallbacks = list.join('|');",
        "  } else {",
        "    img.onerror = null;",
        "  }",
        "}",
        "function renderCoinTrays() {",
        "  const onSvg = \"<svg class='coin-icon' viewBox='0 0 24 24'><use href='#coin-on'/></svg>\";",
        "  const offSvg = \"<svg class='coin-icon' viewBox='0 0 24 24'><use href='#coin-off'/></svg>\";",
        "  document.querySelectorAll('.coin-tray[data-on]').forEach(el => {",
        "    const on = parseInt(el.dataset.on || '0', 10);",
        "    const off = parseInt(el.dataset.off || '0', 10);",
        "    el.innerHTML = onSvg.repeat(Math.max(0, on)) + offSvg.repeat(Math.max(0, off));",
        "  });",
        "}",
        "document.addEventListener('DOMContentLoaded', renderCoinTrays);",
        "function openCardModal(img) {",
        "  const modal = document.getElementById('card-modal');",
        "  const modalImg = document.getElementById('card-modal-img');",
        "  const extra = document.getElementById('card-modal-extra');",
        "  const baseSrc = img.currentSrc || img.src;",
        "  const hiRes = baseSrc.replace('/256x/', '/512x/');",
        "  modalImg.onerror = function() { modalImg.onerror = null; modalImg.src = baseSrc; };",
        "  modalImg.src = hiRes;",
        "  modalImg.alt = img.alt || '';",
        "  extra.innerHTML = '';",
        "  const cardItem = img.closest('.card-item');",
        "  if (cardItem) {",
        "    cardItem.querySelectorAll('.stat-pill, .kw-row, .dg-effect-box').forEach(el => {",
        "      extra.appendChild(el.cloneNode(true));",
        "    });",
        "  }",
        "  modal.classList.add('open');",
        "}",
        "function closeCardModal() {",
        "  const modal = document.getElementById('card-modal');",
        "  if (modal) modal.classList.remove('open');",
        "}",
        "document.addEventListener('click', function(e) {",
        "  const img = e.target.closest('.card-item img, .hero-img, .zoomable-img');",
        "  if (img) { openCardModal(img); return; }",
        "  if (e.target.id === 'card-modal' || e.target.id === 'card-modal-close') { closeCardModal(); }",
        "});",
        "document.addEventListener('keydown', function(e) {",
        "  if (e.key === 'Escape') closeCardModal();",
        "});",
        "</script>",
        "</head>",
        "<body>",
        # コインSVGシンボル定義（インラインなのでオフラインでも表示可能）
        "<svg xmlns='http://www.w3.org/2000/svg' width='0' height='0' style='position:absolute;width:0;height:0;overflow:hidden' aria-hidden='true'>",
        "  <defs>",
        "    <radialGradient id='coin-gold-grad' cx='35%' cy='30%' r='70%'>",
        "      <stop offset='0%' stop-color='#fff6b8'/>",
        "      <stop offset='45%' stop-color='#f7c631'/>",
        "      <stop offset='100%' stop-color='#b87409'/>",
        "    </radialGradient>",
        "    <symbol id='coin-on' viewBox='0 0 24 24'>",
        "      <circle cx='12' cy='12' r='10.5' fill='url(#coin-gold-grad)' stroke='#7a4a04' stroke-width='1.5'/>",
        "      <circle cx='12' cy='12' r='7.4' fill='none' stroke='#fff1a6' stroke-width='1.2' opacity='0.85'/>",
        "      <polygon points='12,6.8 13.5,10.2 17.2,10.5 14.3,12.8 15.2,16.4 12,14.5 8.8,16.4 9.7,12.8 6.8,10.5 10.5,10.2' fill='#9c5b04' opacity='0.75'/>",
        "    </symbol>",
        "    <symbol id='coin-off' viewBox='0 0 24 24'>",
        "      <circle cx='12' cy='12' r='10.5' fill='#282d38' stroke='#4a5264' stroke-width='1.5'/>",
        "      <circle cx='12' cy='12' r='7.4' fill='none' stroke='#3b4252' stroke-width='1.2'/>",
        "    </symbol>",
        "  </defs>",
        "</svg>",
        "<nav class='sticky-nav' aria-label='試合ナビゲーション'>",
        "  <span class='sticky-nav-label'>移動:</span>",
        "  <a class='nav-pill nav-pill-toc' href='#toc'>目次</a>",
    ]

    for game_idx, game in zip(game_numbers, games):
        turn_count = len(game["turns"])
        place = game.get("final_place")
        place_str = f"{place}位・" if place is not None else ""
        html_parts.append(
            f"  <a class='nav-pill' href='#game-{game_idx}'>第 {game_idx} 試合（{place_str}{turn_count}T）</a>"
        )
    html_parts.append("</nav>")
    html_parts.append("<h1>バトルグラウンド 振り返りレポート</h1>")

    # 目次（各試合＋各ターンへのジャンプ）
    toc_title = f"目次（第 {game_numbers[0]} 試合）" if is_single_game else f"目次（全 {len(games)} 試合）"
    html_parts.append("<div id='toc' class='toc-box'>")
    html_parts.append(f"<div class='toc-title'>{toc_title}</div>")
    html_parts.append("<div class='toc-list'>")
    for game_idx, game in zip(game_numbers, games):
        sorted_turns = sorted(game["turns"].keys())
        max_tier = max((game["turns"][t]["tier_end"] for t in sorted_turns), default=1)
        dg_count = sum(len(game["turns"][t]["dark_gifts"]) for t in sorted_turns)
        hero_thumb = (
            build_img_tag(
                game["hero_card_id"],
                css_class="toc-hero-img",
                alt=resolve_card_name(game["hero_card_id"]) or f"Game {game_idx} Hero",
                lazy=False,
                is_hero=True,
            )
            if game["hero_card_id"]
            else ""
        )
        dg_summary = f" / 恵み {dg_count}回" if dg_count else ""
        ban_summary = ""
        if len(game["active_tribes"]) >= 5 and game["banned_tribes"]:
            ban_names = "・".join(BG_TRIBE_LABELS.get(t, t) for t in game["banned_tribes"])
            ban_summary = f" / BAN: {ban_names}"
        toc_place_badge = render_place_badge(game, show_prefix=False)
        html_parts.append("<div class='toc-game'>")
        html_parts.append(
            f"<a class='toc-game-link' href='#game-{game_idx}'>"
            f"{hero_thumb}"
            f"<span>"
            f"<div class='toc-game-name'><span>第 {game_idx} 試合</span>{toc_place_badge}</div>"
            f"<div class='toc-game-meta'>全 {len(sorted_turns)} ターン / 最大 ★{max_tier}{dg_summary}{ban_summary}</div>"
            f"</span>"
            f"</a>"
        )
        html_parts.append("<div class='toc-turns'>")
        for t in sorted_turns:
            td = game["turns"][t]
            has_dg = bool(td["dark_gifts"])
            t_cls = "toc-turn-link toc-turn-dg" if has_dg else "toc-turn-link"
            dg_mark = "✦" if has_dg else ""
            html_parts.append(
                f"<a class='{t_cls}' href='#game-{game_idx}-turn-{t}' title='第{game_idx}試合 ターン{t}（★{td['tier_start']}→★{td['tier_end']}）'>"
                f"T{t}{dg_mark}</a>"
            )
        html_parts.append("</div></div>")
    html_parts.append("</div></div>")

    def append_dark_gift_block(dg_ev):
        r_idx = dg_ev["roll_index"]
        timing = "リロール前" if r_idx == 0 else f"{r_idx}回目リロール後"
        dg_gold_html = render_coins(dg_ev["gold"], dg_ev["max_gold"], label="発見時")
        html_parts.append("<div class='dg-block'>")
        html_parts.append(
            f"<div class='dg-header'>"
            f"<span>✦ 悪夢の恵み（発見・{timing}）</span>"
            f"<span class='roll-gold-bar'>{dg_gold_html}</span>"
            f"</div>"
        )
        html_parts.append("<div class='card-row'>")
        for opt in dg_ev["options"]:
            is_chosen = opt["eid"] == dg_ev["chosen_eid"]
            cls_list = ["card-item", "dg-option"]
            cls_list.append("dg-option-chosen" if is_chosen else "dg-option-unchosen")
            if opt["golden"]:
                cls_list.append("golden")
            badge_html = "<span class='badge badge-dg-chosen'>選択</span>" if is_chosen else ""
            html_parts.append(
                f"<div class='{' '.join(cls_list)}'>"
                f"{badge_html}"
                f"{build_img_tag(opt['card_id'])}"
                f"{render_dark_gift_box(opt['dark_gifts'])}"
                f"</div>"
            )
        html_parts.append("</div></div>")

    for game_idx, game in zip(game_numbers, games):
        html_parts.append(f"<div id='game-{game_idx}' class='game-header'>")
        if game["hero_card_id"]:
            html_parts.append(
                build_img_tag(
                    game["hero_card_id"],
                    css_class="hero-img",
                    alt=resolve_card_name(game["hero_card_id"]) or "Hero",
                    lazy=False,
                    is_hero=True,
                )
            )
        header_place_badge = render_place_badge(game, show_prefix=True)
        html_parts.append(f"<h2><span>第 {game_idx} 試合</span>{header_place_badge}</h2>")
        html_parts.append("<a class='back-to-toc' href='#toc'>↑ 目次へ</a>")
        html_parts.append("</div>")

        # 試合情報（種族BAN・開始時ヒーロー選択肢）
        if game["active_tribes"] or game["hero_choices"]:
            html_parts.append("<div class='game-info-box'>")

            # 種族（出現 / BAN）
            if game["active_tribes"] or game["banned_tribes"]:
                active_cnt = len(game["active_tribes"])
                is_complete = active_cnt >= 5
                active_label = f"出現種族（{active_cnt}）" if is_complete else f"確認できた種族（{active_cnt}/5）"
                ban_label = f"BAN種族（{len(game['banned_tribes'])}）" if is_complete else f"未出現 / BAN候補（{len(game['banned_tribes'])}）"
                note_html = (
                    "<span class='game-info-note'>※ Power.log にはBAN一覧が直接記録されないため、試合中に出現した単一種族ミニオンから推定しています</span>"
                    if is_complete
                    else "<span class='game-info-note'>※ 早期終了のため全5種族はログ未出現（出現した単一種族ミニオンから推定）</span>"
                )
                active_chips = "".join(
                    f"<span class='tribe-chip tribe-active'>{html.escape(BG_TRIBE_LABELS.get(t, t))}</span>"
                    for t in game["active_tribes"]
                )
                ban_chips = "".join(
                    f"<span class='tribe-chip tribe-ban'>{html.escape(BG_TRIBE_LABELS.get(t, t))}</span>"
                    for t in game["banned_tribes"]
                )
                html_parts.append("<div class='game-info-section'>")
                html_parts.append(f"<div class='game-info-title'>種族プール / BAN情報 {note_html}</div>")
                html_parts.append("<div class='tribe-rows'>")
                html_parts.append(
                    f"<div class='tribe-line'><span class='tribe-line-label'>{active_label}</span>{active_chips}</div>"
                )
                html_parts.append(
                    f"<div class='tribe-line'><span class='tribe-line-label'>{ban_label}</span>{ban_chips}</div>"
                )
                html_parts.append("</div></div>")

            # 開始時ヒーロー選択肢
            if game["hero_choices"]:
                html_parts.append("<div class='game-info-section'>")
                html_parts.append("<div class='game-info-title'>試合開始時のヒーロー選択肢</div>")
                html_parts.append("<div class='hero-choices-row'>")
                # 選択可能（未ロック）を先、ロック枠を後に並べる
                ordered_heroes = sorted(game["hero_choices"], key=lambda h: (h["locked"], not h["chosen"]))
                for h_opt in ordered_heroes:
                    slot_cls = ["hero-choice-slot"]
                    if h_opt["chosen"]:
                        slot_cls.append("is-chosen")
                    if h_opt["locked"]:
                        slot_cls.append("is-locked")
                    html_parts.append(f"<div class='{' '.join(slot_cls)}'>")
                    hist = h_opt["history"]
                    if len(hist) > 1:
                        # リロール前のヒーローを表示
                        for prev_cid in hist[:-1]:
                            html_parts.append(
                                f"<div class='card-item hero-choice-rerolled-from'>"
                                f"<span class='badge badge-reroll-from'>リロール前</span>"
                                f"{build_img_tag(prev_cid, is_hero=True)}"
                                f"</div>"
                                f"<span class='hero-reroll-arrow'>→</span>"
                            )
                    badge_html = ""
                    if h_opt["chosen"]:
                        badge_html = "<span class='badge badge-buy'>選択</span>"
                    elif h_opt["locked"]:
                        badge_html = "<span class='badge badge-locked'>ロック</span>"
                    html_parts.append(
                        f"<div class='card-item hero-choice-card'>"
                        f"{badge_html}"
                        f"{build_img_tag(h_opt['final_card_id'], is_hero=True)}"
                        f"</div>"
                    )
                    html_parts.append("</div>")
                html_parts.append("</div></div>")

            html_parts.append("</div>")

        for turn in sorted(game["turns"].keys()):
            t_data = game["turns"][turn]
            rolls = t_data["rolls"]
            dg_events_by_roll = {}
            for dg_ev in t_data["dark_gifts"]:
                dg_events_by_roll.setdefault(dg_ev["roll_index"], []).append(dg_ev)

            start_gold_html = render_coins(
                t_data["gold_start"], t_data["max_gold_start"], label="開始時"
            )
            tier_html = render_tier_badge(
                t_data["tier_start"], t_data["tier_end"], t_data["upgrade_cost_start"]
            )
            reroll_meta = f"リロール: {max(0, len(rolls) - 1)}回"

            # ターン見出し用の自ライフ（ターン開始時）＆対戦相手プレビュー
            life_header_html = ""
            combat = t_data.get("combat")
            hp_for_header = (
                t_data.get("my_hp_start")
                or (combat.get("my_hp_before") if combat else None)
                or t_data.get("my_hp_end_recruit")
            )
            if hp_for_header:
                life_header_html = (
                    f"<span class='life-pill' title='ターン開始時の残りライフ（体力+装甲）'>"
                    f"<span class='tier-label'>自ライフ</span>"
                    f"{render_life_span(hp_for_header[0], hp_for_header[1])}"
                    f"</span>"
                )
            opp_preview_html = ""
            opp_entry = next((p for p in t_data.get("leaderboard", []) if p["is_opponent"]), None)
            if opp_entry:
                opp_name = html.escape(resolve_hero_name(opp_entry))
                opp_thumb = build_img_tag(
                    opp_entry["card_id"],
                    css_class="vs-mini-img zoomable-img",
                    alt=resolve_hero_name(opp_entry),
                    is_hero=True,
                )
                opp_tier_txt = f"★{opp_entry['tier_start']}→★{opp_entry['tier_end']}"
                opp_preview_html = (
                    f"<span class='vs-pill' title='このターンの対戦相手と酒場グレード推移'>"
                    f"{opp_thumb}<span>VS {opp_name} ({opp_tier_txt})</span>"
                    f"</span>"
                )

            html_parts.append(f"<div id='game-{game_idx}-turn-{turn}' class='turn-box'>")
            html_parts.append(
                f"<div class='turn-title'>"
                f"<span>ターン {turn}</span>"
                f"<span class='turn-meta'>{tier_html}{start_gold_html}{life_header_html}{opp_preview_html}<span>({reroll_meta})</span></span>"
                f"</div>"
            )

            rendered_dg_rolls = set()
            for roll in rolls:
                idx = roll["roll_index"]
                roll_label = "リロール前（初期提示）" if idx == 0 else f"{idx}回目リロール後"

                roll_gold_html = render_coins(
                    roll["gold_start"], roll["max_gold_start"], label="ロール時"
                )
                if (
                    roll["gold_end"] != roll["gold_start"]
                    or roll["max_gold_end"] != roll["max_gold_start"]
                ):
                    roll_gold_html += (
                        "<span class='gold-arrow'>→</span>"
                        + render_coins(roll["gold_end"], roll["max_gold_end"], label="行動後")
                    )

                html_parts.append("<div class='roll-block'>")
                html_parts.append(
                    f"<div class='roll-header'>"
                    f"<span>{roll_label}</span>"
                    f"<span class='roll-gold-bar'>{roll_gold_html}</span>"
                    f"</div>"
                )
                html_parts.append("<div class='roll-content'>")

                html_parts.append("<div class='sub-group'>")
                html_parts.append("<div class='sub-label'>酒場のラインナップ</div>")
                html_parts.append("<div class='card-row'>")

                for cid in roll["carried_over"]:
                    html_parts.append(
                        f"<div class='card-item frozen'>"
                        f"<span class='badge badge-freeze'>凍結継続</span>"
                        f"{build_img_tag(cid)}"
                        f"</div>"
                    )

                for cid in roll["offered"]:
                    html_parts.append(
                        f"<div class='card-item'>"
                        f"{build_img_tag(cid)}"
                        f"</div>"
                    )

                html_parts.append("</div></div>")

                html_parts.append("<div class='sub-group'>")
                html_parts.append("<div class='sub-label'>このロールで購入</div>")
                html_parts.append("<div class='card-row'>")
                if roll["bought"]:
                    for cid in roll["bought"]:
                        html_parts.append(
                            f"<div class='card-item bought'>"
                            f"<span class='badge badge-buy'>購入</span>"
                            f"{build_img_tag(cid)}"
                            f"</div>"
                        )
                else:
                    html_parts.append("<span class='empty-note'>購入なし</span>")
                html_parts.append("</div></div>")

                html_parts.append("</div></div>")

                # このロール中に行われた「悪夢の恵み」発見を表示
                if idx in dg_events_by_roll:
                    rendered_dg_rolls.add(idx)
                    for dg_ev in dg_events_by_roll[idx]:
                        append_dark_gift_block(dg_ev)

            # ロールに紐づかなかった恵み発見があればここで表示
            for r_idx, dg_list in sorted(dg_events_by_roll.items()):
                if r_idx not in rendered_dg_rolls:
                    for dg_ev in dg_list:
                        append_dark_gift_block(dg_ev)

            # ターン終了時の自分の盤面ミニオン・手札・残り所持金・終了時グレード（戦闘ブロック内に埋め込み用）
            end_gold_html = render_coins(
                t_data["gold_end"], t_data["max_gold_end"], label="残り"
            )
            end_tier_html = (
                f"<span class='tier-badge'>"
                f"<span class='tier-label'>終了時グレード</span>"
                f"<span class='tier-val'>★{t_data['tier_end']}</span>"
                f"</span>"
            )
            board = t_data["board_end"]
            hand = t_data["hand_end"]

            end_turn_parts = [
                "<div class='end-turn-block'>",
                (
                    f"<div class='end-turn-header'>"
                    f"<span>ターン終了時の状況</span>"
                    f"<span class='roll-gold-bar'>{end_tier_html}{end_gold_html}</span>"
                    f"</div>"
                ),
                "<div class='end-turn-content'>",
                "<div class='sub-group'>",
                f"<div class='sub-label'>自分のミニオン（{len(board)}体）</div>",
                "<div class='card-row'>",
            ]
            if board:
                for m in board:
                    end_turn_parts.append(render_minion_card(m))
            else:
                end_turn_parts.append("<span class='empty-note'>ミニオンなし</span>")
            end_turn_parts.append("</div></div>")

            end_turn_parts.append("<div class='sub-group'>")
            end_turn_parts.append(f"<div class='sub-label'>手札（{len(hand)}枚）</div>")
            end_turn_parts.append("<div class='card-row'>")
            if hand:
                for h_card in hand:
                    cls_list = ["card-item"]
                    if h_card["golden"]:
                        cls_list.append("golden")
                    if h_card["dark_gifts"]:
                        cls_list.append("has-dg")
                    stat_html = ""
                    if h_card["card_type"] == "MINION":
                        stat_html = (
                            f"<div class='stat-pill'>"
                            f"<span class='stat-atk'>{h_card['atk']}</span>"
                            f"<span class='stat-hp'>{h_card['health']}</span>"
                            f"</div>"
                        )
                    end_turn_parts.append(
                        f"<div class='{' '.join(cls_list)}'>"
                        f"{build_img_tag(h_card['card_id'])}"
                        f"{stat_html}"
                        f"{render_dark_gift_box(h_card['dark_gifts'])}"
                        f"</div>"
                    )
            else:
                end_turn_parts.append("<span class='empty-note'>手札なし</span>")
            end_turn_parts.append("</div></div>")
            end_turn_parts.append("</div></div>")

            # ロビー全員（自分＋敵7人）のリーダーボード一覧（折りたたみ・戦闘前）
            lb_list = t_data.get("leaderboard", [])
            if lb_list:
                html_parts.append("<details class='lb-details'>")
                html_parts.append(
                    f"<summary>ロビー全員の状況（全{len(lb_list)}人：順位・開始/終了グレード・体力・トリプル・装飾品）</summary>"
                )
                html_parts.append("<div class='lb-table-wrap'><table class='lb-table'>")
                html_parts.append(
                    "<thead><tr>"
                    "<th>順位</th><th>ヒーロー</th><th>酒場グレード</th><th>体力 / 装甲</th><th>トリプル</th><th>装飾品</th>"
                    "</tr></thead><tbody>"
                )
                for p in lb_list:
                    r_cls = []
                    if p["is_me"]:
                        r_cls.append("lb-row-me")
                    elif p["is_opponent"]:
                        r_cls.append("lb-row-opp")
                    if p["hp"] <= 0:
                        r_cls.append("lb-row-dead")
                    tr_attr = f" class='{' '.join(r_cls)}'" if r_cls else ""
                    p_name = html.escape(resolve_hero_name(p))
                    p_img = build_img_tag(
                        p["card_id"],
                        css_class="lb-hero-img zoomable-img",
                        alt=resolve_hero_name(p),
                        is_hero=True,
                    )
                    role_tag = ""
                    if p["is_me"]:
                        role_tag = "<span class='lb-tag-me'>自分</span>"
                    elif p["is_opponent"]:
                        role_tag = "<span class='lb-tag-opp'>対戦相手</span>"
                    t_up = p["tier_end"] > p["tier_start"]
                    t_cls = "opp-meta-chip opp-tier-up" if t_up else "opp-meta-chip"
                    up_s = " UP" if t_up else ""
                    tr_html = (
                        render_trinket_chip(p["trinket1"], "下級")
                        + render_trinket_chip(p["trinket2"], "上級")
                    ) or "<span style='color:#6c7586;'>—</span>"
                    html_parts.append(
                        f"<tr{tr_attr}>"
                        f"<td><strong>{p['place']}位</strong></td>"
                        f"<td><span class='lb-hero-cell'>{p_img}<span>{p_name}</span>{role_tag}</span></td>"
                        f"<td><span class='{t_cls}'>★{p['tier_start']} → ★{p['tier_end']}{up_s}</span></td>"
                        f"<td>{render_life_span(p['hp'], p['armor'])}</td>"
                        f"<td>{p['triples']}回</td>"
                        f"<td><div class='trinket-row'>{tr_html}</div></td>"
                        f"</tr>"
                    )
                html_parts.append("</tbody></table></div></details>")

            # 戦闘結果・対戦相手の盤面＆情報（ターン終了時の状況を内包）
            if combat:
                res = combat["result"]
                dmg = combat["damage"]
                if res == "WIN":
                    res_html = f"<span class='combat-res-badge combat-res-win'>勝利 (+{dmg})</span>"
                elif res == "LOSS":
                    res_html = f"<span class='combat-res-badge combat-res-loss'>敗北 (-{dmg})</span>"
                else:
                    res_html = "<span class='combat-res-badge combat-res-tie'>引き分け</span>"

                my_before = combat.get("my_hp_before")
                my_after = combat.get("my_hp_after")
                life_diff_html = ""
                if my_before and my_after:
                    if my_before != my_after:
                        life_diff_html = (
                            f"<span class='life-pill'>"
                            f"<span class='tier-label'>自ライフ</span>"
                            f"{render_life_span(my_before[0], my_before[1])}"
                            f"<span class='gold-arrow'>→</span>"
                            f"{render_life_span(my_after[0], my_after[1])}"
                            f"</span>"
                        )
                    else:
                        life_diff_html = (
                            f"<span class='life-pill'>"
                            f"<span class='tier-label'>自ライフ</span>"
                            f"{render_life_span(my_after[0], my_after[1])}"
                            f"</span>"
                        )

                html_parts.append("<div class='combat-block'>")
                html_parts.append(
                    f"<div class='combat-header'>"
                    f"<span>⚔ 戦闘結果・対戦相手</span>"
                    f"<span class='roll-gold-bar'>{res_html}{life_diff_html}</span>"
                    f"</div>"
                )

                opp_h = combat.get("opp_hero")
                if opp_h:
                    opp_name = html.escape(resolve_hero_name(opp_h))
                    opp_img = build_img_tag(
                        opp_h["card_id"],
                        css_class="opp-hero-thumb zoomable-img",
                        alt=resolve_hero_name(opp_h),
                        is_hero=True,
                    )
                    meta_chips = []
                    if opp_h.get("place"):
                        meta_chips.append(f"<span class='opp-meta-chip'>順位 {opp_h['place']}位</span>")
                    if "tier_start" in opp_h and "tier_end" in opp_h:
                        t_up = opp_h["tier_end"] > opp_h["tier_start"]
                        t_cls = "opp-meta-chip opp-tier-up" if t_up else "opp-meta-chip"
                        up_s = " UP" if t_up else ""
                        meta_chips.append(
                            f"<span class='{t_cls}'>グレード ★{opp_h['tier_start']} → ★{opp_h['tier_end']}{up_s}</span>"
                        )
                    if "hp" in opp_h:
                        meta_chips.append(
                            f"<span class='opp-meta-chip'>体力 {render_life_span(opp_h['hp'], opp_h.get('armor', 0))}</span>"
                        )
                    if "triples" in opp_h:
                        meta_chips.append(f"<span class='opp-meta-chip'>トリプル {opp_h['triples']}回</span>")

                    tr_chips = (
                        render_trinket_chip(opp_h.get("trinket1", 0), "下級")
                        + render_trinket_chip(opp_h.get("trinket2", 0), "上級")
                    )
                    tr_html = f"<div class='trinket-row'>{tr_chips}</div>" if tr_chips else ""

                    html_parts.append("<div class='opp-summary-card'>")
                    html_parts.append(opp_img)
                    html_parts.append("<div class='opp-summary-info'>")
                    html_parts.append(f"<div class='opp-summary-top'><span>{opp_name}</span>{''.join(meta_chips)}</div>")
                    html_parts.append(tr_html)
                    html_parts.append("</div></div>")

                opp_board = combat.get("opp_board", [])
                html_parts.append("<div class='sub-group'>")
                html_parts.append(f"<div class='sub-label'>相手の盤面（{len(opp_board)}体）</div>")
                html_parts.append("<div class='card-row'>")
                if opp_board:
                    for om in opp_board:
                        html_parts.append(render_minion_card(om))
                else:
                    html_parts.append("<span class='empty-note'>ミニオンなし</span>")
                html_parts.append("</div></div>")
                html_parts.extend(end_turn_parts)
                html_parts.append("</div>")
            else:
                html_parts.extend(end_turn_parts)

            html_parts.append("</div>")

    # このレポートに登場した CardID の日本語名・効果テキスト辞書を非表示 JSON として埋め込む
    catalog_entries = build_catalog_entries(used_card_ids, card_catalog)

    catalog_lines = ["{"]
    sorted_items = list(catalog_entries.items())
    for i, (cid, item) in enumerate(sorted_items):
        comma = "," if i < len(sorted_items) - 1 else ""
        line_json = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        catalog_lines.append(f"  {json.dumps(cid, ensure_ascii=False)}: {line_json}{comma}")
    catalog_lines.append("}")
    safe_catalog_json = "\n".join(catalog_lines).replace("</", "<\\/")

    html_parts.extend([
        "<div id='card-modal' class='card-modal' role='dialog' aria-modal='true'>",
        "  <div class='card-modal-inner'>",
        "    <button id='card-modal-close' class='card-modal-close' type='button' aria-label='閉じる'>&times;</button>",
        "    <img id='card-modal-img' class='card-modal-img' src='' alt=''>",
        "    <div id='card-modal-extra' class='card-modal-extra'></div>",
        "    <div class='card-modal-hint'>背景クリック または Esc キーで閉じる</div>",
        "  </div>",
        "</div>",
        "<script id='card-catalog' type='application/json'>",
        safe_catalog_json,
        "</script>",
        "</body>",
        "</html>",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))


def build_catalog_entries(used_card_ids, card_catalog):
    """登場した CardID の日本語名・種別・グレード・効果・ヒーローパワー辞書を構築する"""
    by_card_id = card_catalog.get("by_card_id", {})
    by_dbf_id = card_catalog.get("by_dbf_id", {})
    catalog_entries = {}
    for cid in sorted(used_card_ids):
        direct = by_card_id.get(cid)
        info = direct or (by_card_id.get(cid[:-2]) if cid.endswith("_G") else None)
        if not info:
            continue
        item = {"name": info["name"]}
        if cid.endswith("_G") and direct is None:
            item["golden"] = True
        if info.get("type"):
            item["type"] = info["type"]
        if info.get("tier") is not None:
            item["tier"] = info["tier"]
        if info.get("cost") is not None and info.get("type") != "MINION":
            item["cost"] = info["cost"]
        if info.get("tribes"):
            item["tribes"] = info["tribes"]
        if info.get("type") == "MINION":
            if info.get("atk") is not None:
                item["atk"] = info["atk"]
            if info.get("hp") is not None:
                item["hp"] = info["hp"]
        if info.get("text"):
            item["text"] = info["text"]
        hp_dbf = info.get("hero_power_dbf_id")
        if hp_dbf is not None:
            hp_info = by_dbf_id.get(int(hp_dbf))
            if hp_info:
                hp_obj = {"id": hp_info["id"], "name": hp_info["name"]}
                if hp_info.get("cost") is not None:
                    hp_obj["cost"] = hp_info["cost"]
                if hp_info.get("text"):
                    hp_obj["text"] = hp_info["text"]
                item["hero_power"] = hp_obj
        catalog_entries[cid] = item
    return catalog_entries


def generate_ai_text(games, output_path, card_catalog=None, game_numbers=None):
    """HTMLと同等の情報をCSS/タグなしで超軽量にまとめたAI分析用Markdownを出力する"""
    if card_catalog is None:
        card_catalog = fetch_card_catalog()
    if game_numbers is None:
        game_numbers = list(range(1, len(games) + 1))

    dark_gift_db = card_catalog.get("dark_gifts", {})
    by_dbf_id = card_catalog.get("by_dbf_id", {})
    by_card_id = card_catalog.get("by_card_id", {})
    used_card_ids = set()
    used_dg_ids = set()

    def use_card(cid):
        if cid:
            used_card_ids.add(cid)
        return cid

    def resolve_name(cid):
        if not cid:
            return "不明"
        use_card(cid)
        info = by_card_id.get(cid) or (by_card_id.get(cid[:-2]) if cid.endswith("_G") else None)
        return info["name"] if info and info.get("name") else cid

    def resolve_hero(entry):
        if not entry:
            return "不明"
        cid = entry.get("card_id", "")
        if cid:
            use_card(cid)
        if entry.get("name"):
            return entry["name"]
        return resolve_name(cid) if cid else "不明"

    def resolve_trinket(dbf_id, slot_label):
        if not dbf_id:
            return ""
        info = by_dbf_id.get(int(dbf_id))
        if info:
            use_card(info["id"])
            return f"{slot_label}:{info['name']}"
        return f"{slot_label}:ID{dbf_id}"

    def fmt_life(hp, armor):
        if hp is None:
            return "?"
        if hp <= 0:
            return "脱落"
        return f"{hp}+{armor}" if armor and armor > 0 else str(hp)

    def fmt_gold(gold, max_gold):
        if gold is None:
            return "?"
        return f"{gold}/{max_gold}" if max_gold is not None else str(gold)

    def fmt_dg_names(dg_ids, with_desc=False):
        if not dg_ids:
            return ""
        parts = []
        seen = set()
        for dg_cid in dg_ids:
            used_dg_ids.add(dg_cid)
            name, desc = dark_gift_db.get(dg_cid, (dg_cid, ""))
            if (name, desc) in seen:
                continue
            seen.add((name, desc))
            if with_desc and desc:
                parts.append(f"✦{name}: {desc}")
            else:
                parts.append(f"✦{name}")
        return " / ".join(parts)

    def fmt_minion(m, idx=None):
        prefix = f"{idx}." if idx is not None else ""
        gold_tag = "[金]" if m.get("golden") else ""
        name = resolve_name(m["card_id"])
        kws = []
        if m.get("taunt"):
            kws.append("挑発")
        if m.get("divine_shield"):
            kws.append("聖盾")
        if m.get("reborn"):
            kws.append("蘇り")
        if m.get("poisonous"):
            kws.append("猛毒")
        if m.get("venomous"):
            kws.append("毒袋")
        if m.get("windfury"):
            kws.append("疾風")
        kw_s = f"[{'/'.join(kws)}]" if kws else ""
        dg_s = fmt_dg_names(m.get("dark_gifts", []), with_desc=False)
        dg_part = f"{{{dg_s}}}" if dg_s else ""
        return f"{prefix}{gold_tag}{name}({m['atk']}/{m['health']}){kw_s}{dg_part}"

    def fmt_hand_card(h_card):
        gold_tag = "[金]" if h_card.get("golden") else ""
        name = resolve_name(h_card["card_id"])
        stat_s = f"({h_card['atk']}/{h_card['health']})" if h_card.get("card_type") == "MINION" else ""
        dg_s = fmt_dg_names(h_card.get("dark_gifts", []), with_desc=False)
        dg_part = f"{{{dg_s}}}" if dg_s else ""
        return f"{gold_tag}{name}{stat_s}{dg_part}"

    def fmt_trinkets(entry):
        items = [
            resolve_trinket(entry.get("trinket1", 0), "下級"),
            resolve_trinket(entry.get("trinket2", 0), "上級"),
        ]
        items = [x for x in items if x]
        return ", ".join(items)

    lines = ["# バトルグラウンド振り返りログ（AI分析用）", ""]

    for game_idx, game in zip(game_numbers, games):
        sorted_turns = sorted(game["turns"].keys())
        max_tier = max((game["turns"][t]["tier_end"] for t in sorted_turns), default=1)
        hero_name = resolve_name(game["hero_card_id"]) if game.get("hero_card_id") else "不明"
        place = game.get("final_place")
        if place is not None:
            suffix = "" if game.get("game_completed", False) else "（途中終了）"
            place_str = f"最終順位: {place}位{suffix}"
        else:
            place_str = "最終順位: 不明"

        lines.append(f"## 第 {game_idx} 試合｜{hero_name}｜{place_str}（全{len(sorted_turns)}ターン / 最大★{max_tier}）")

        # 種族プール / BAN
        if game["active_tribes"] or game["banned_tribes"]:
            active_cnt = len(game["active_tribes"])
            is_complete = active_cnt >= 5
            active_lbl = f"出現種族({active_cnt})" if is_complete else f"確認できた種族({active_cnt}/5)"
            ban_lbl = f"BAN種族({len(game['banned_tribes'])})" if is_complete else f"未出現/BAN候補({len(game['banned_tribes'])})"
            active_str = "・".join(BG_TRIBE_LABELS.get(t, t) for t in game["active_tribes"]) or "なし"
            ban_str = "・".join(BG_TRIBE_LABELS.get(t, t) for t in game["banned_tribes"]) or "なし"
            lines.append(f"- {active_lbl}: {active_str} ｜ {ban_lbl}: {ban_str}")

        # 開始時ヒーロー選択肢
        if game["hero_choices"]:
            ordered_heroes = sorted(game["hero_choices"], key=lambda h: (h["locked"], not h["chosen"]))
            choice_parts = []
            for h_opt in ordered_heroes:
                tag = "[選択]" if h_opt["chosen"] else ("[ロック]" if h_opt["locked"] else "")
                final_cid = h_opt["final_card_id"]
                final_s = f"{tag}{resolve_name(final_cid)}({final_cid})"
                hist = h_opt["history"]
                if len(hist) > 1:
                    prev_s = "→".join(f"{resolve_name(pc)}({pc})" for pc in hist[:-1])
                    final_s = f"{final_s} ←リロール前:{prev_s}"
                choice_parts.append(final_s)
            lines.append(f"- ヒーロー選択肢: {' | '.join(choice_parts)}")

        lines.append("")

        for turn in sorted_turns:
            t_data = game["turns"][turn]
            rolls = t_data["rolls"]
            reroll_cnt = max(0, len(rolls) - 1)
            up_cost = f"UP費{t_data['upgrade_cost_start']}" if t_data["upgrade_cost_start"] is not None else "UP費MAX"
            tier_up_mark = " UP" if t_data["tier_end"] > t_data["tier_start"] else ""
            start_gold_s = fmt_gold(t_data["gold_start"], t_data["max_gold_start"])

            combat = t_data.get("combat")
            hp_for_header = (
                t_data.get("my_hp_start")
                or (combat.get("my_hp_before") if combat else None)
                or t_data.get("my_hp_end_recruit")
            )
            life_s = fmt_life(hp_for_header[0], hp_for_header[1]) if hp_for_header else "?"

            opp_entry = next((p for p in t_data.get("leaderboard", []) if p["is_opponent"]), None)
            if opp_entry:
                opp_hdr = f"VS {resolve_hero(opp_entry)}(★{opp_entry['tier_start']}→★{opp_entry['tier_end']})"
            else:
                opp_hdr = "VS 不明"

            lines.append(
                f"### T{turn}｜★{t_data['tier_start']}→★{t_data['tier_end']}{tier_up_mark} ({up_cost})"
                f"｜開始金 {start_gold_s}｜自ライフ {life_s}｜{opp_hdr}｜リロール {reroll_cnt}回"
            )

            dg_events_by_roll = {}
            for dg_ev in t_data["dark_gifts"]:
                dg_events_by_roll.setdefault(dg_ev["roll_index"], []).append(dg_ev)

            def append_dg_line(dg_ev):
                r_idx = dg_ev["roll_index"]
                timing = "リロール前" if r_idx == 0 else f"R{r_idx}後"
                gold_s = fmt_gold(dg_ev["gold"], dg_ev["max_gold"])
                opt_parts = []
                for opt in dg_ev["options"]:
                    chosen_tag = "[選択]" if opt["eid"] == dg_ev["chosen_eid"] else ""
                    gold_tag = "[金]" if opt.get("golden") else ""
                    c_name = resolve_name(opt["card_id"])
                    dg_desc = fmt_dg_names(opt.get("dark_gifts", []), with_desc=True)
                    dg_part = f"({dg_desc})" if dg_desc else ""
                    opt_parts.append(f"{chosen_tag}{gold_tag}{c_name}{dg_part}")
                lines.append(f"- 悪夢の恵み({timing}, 金{gold_s}): {' | '.join(opt_parts)}")

            rendered_dg_rolls = set()
            for roll in rolls:
                idx = roll["roll_index"]
                r_lbl = "R0(初期)" if idx == 0 else f"R{idx}"
                g_start = fmt_gold(roll["gold_start"], roll["max_gold_start"])
                g_end = fmt_gold(roll["gold_end"], roll["max_gold_end"])
                g_part = f"{g_start}→{g_end}" if g_end != g_start else g_start

                shop_items = [f"[凍結]{resolve_name(cid)}" for cid in roll["carried_over"]]
                shop_items.extend(resolve_name(cid) for cid in roll["offered"])
                shop_str = ", ".join(shop_items) if shop_items else "なし"
                bought_str = ", ".join(resolve_name(cid) for cid in roll["bought"]) if roll["bought"] else "なし"
                lines.append(f"- {r_lbl} ({g_part}) 酒場: {shop_str} ｜ 購入: {bought_str}")

                if idx in dg_events_by_roll:
                    rendered_dg_rolls.add(idx)
                    for dg_ev in dg_events_by_roll[idx]:
                        append_dg_line(dg_ev)

            for r_idx, dg_list in sorted(dg_events_by_roll.items()):
                if r_idx not in rendered_dg_rolls:
                    for dg_ev in dg_list:
                        append_dg_line(dg_ev)

            # ターン終了時の自分の盤面・手札文字列を準備
            end_gold_s = fmt_gold(t_data["gold_end"], t_data["max_gold_end"])
            board = t_data["board_end"]
            hand = t_data["hand_end"]
            board_str = " / ".join(fmt_minion(m, i) for i, m in enumerate(board, start=1)) if board else "なし"
            hand_str = ", ".join(fmt_hand_card(h) for h in hand) if hand else "なし"

            # ロビー全員の状況（戦闘前・1行に圧縮）
            lb_list = t_data.get("leaderboard", [])
            if lb_list:
                lb_parts = []
                for p in lb_list:
                    role = "[自]" if p["is_me"] else ("[敵]" if p["is_opponent"] else "")
                    t_s = f"★{p['tier_start']}→{p['tier_end']}" if p["tier_end"] != p["tier_start"] else f"★{p['tier_end']}"
                    tr_s = fmt_trinkets(p)
                    tr_part = f",{tr_s}" if tr_s else ""
                    lb_parts.append(
                        f"{p['place']}位:{role}{resolve_hero(p)}({t_s},{fmt_life(p['hp'], p['armor'])},T{p['triples']}{tr_part})"
                    )
                lines.append(f"- ロビー: {' / '.join(lb_parts)}")

            # 戦闘結果・相手盤面（ターン終了時の自分の盤面・手札を内包）
            if combat:
                res = combat["result"]
                dmg = combat["damage"]
                res_s = f"勝利(+{dmg})" if res == "WIN" else (f"敗北(-{dmg})" if res == "LOSS" else "引き分け")
                my_before = combat.get("my_hp_before")
                my_after = combat.get("my_hp_after")
                if my_before and my_after:
                    b_s = fmt_life(my_before[0], my_before[1])
                    a_s = fmt_life(my_after[0], my_after[1])
                    life_diff = f"{b_s}→{a_s}" if b_s != a_s else a_s
                elif my_after:
                    life_diff = fmt_life(my_after[0], my_after[1])
                else:
                    life_diff = "?"

                opp_h = combat.get("opp_hero")
                opp_info = ""
                if opp_h:
                    opp_parts = [resolve_hero(opp_h)]
                    if opp_h.get("place"):
                        opp_parts.append(f"{opp_h['place']}位")
                    if "tier_start" in opp_h and "tier_end" in opp_h:
                        opp_parts.append(f"★{opp_h['tier_start']}→★{opp_h['tier_end']}")
                    if "hp" in opp_h:
                        opp_parts.append(f"HP{fmt_life(opp_h['hp'], opp_h.get('armor', 0))}")
                    if "triples" in opp_h:
                        opp_parts.append(f"トリプル{opp_h['triples']}")
                    tr_s = fmt_trinkets(opp_h)
                    if tr_s:
                        opp_parts.append(tr_s)
                    opp_info = f" ｜ 相手: {' / '.join(opp_parts)}"

                lines.append(f"- 戦闘: {res_s} ｜ 自ライフ {life_diff}{opp_info}")
                opp_board = combat.get("opp_board", [])
                opp_board_str = " / ".join(fmt_minion(om, i) for i, om in enumerate(opp_board, start=1)) if opp_board else "なし"
                lines.append(f"  - 相手盤面(左→右,{len(opp_board)}体): {opp_board_str}")
                lines.append(f"  - 自分盤面(終了時★{t_data['tier_end']}, 残金{end_gold_s}, 左→右,{len(board)}体): {board_str}")
                if hand:
                    lines.append(f"  - 手札({len(hand)}枚): {hand_str}")
            else:
                lines.append(f"- 終了時(★{t_data['tier_end']}, 残金{end_gold_s}) 盤面(左→右,{len(board)}体): {board_str}")
                if hand:
                    lines.append(f"  - 手札({len(hand)}枚): {hand_str}")

            lines.append("")

    # 登場カード辞書（カテゴリ別に整形）
    catalog_entries = build_catalog_entries(used_card_ids, card_catalog)
    heroes_cat = []
    minions_cat = []
    spells_cat = []
    trinkets_cat = []
    others_cat = []

    for cid, item in catalog_entries.items():
        ctype = item.get("type", "")
        if ctype == "HERO":
            heroes_cat.append((cid, item))
        elif ctype == "MINION":
            minions_cat.append((cid, item))
        elif ctype == "BATTLEGROUND_SPELL":
            spells_cat.append((cid, item))
        elif ctype == "BATTLEGROUND_TRINKET":
            trinkets_cat.append((cid, item))
        else:
            others_cat.append((cid, item))

    lines.append("## 登場カード辞書（このログに出現したカードのみ）")
    lines.append("")

    if heroes_cat:
        lines.append("### ヒーロー・ヒーローパワー")
        for cid, item in sorted(heroes_cat, key=lambda x: x[1]["name"]):
            hp = item.get("hero_power")
            if hp:
                hp_cost = f"({hp['cost']}G) " if hp.get("cost") is not None else ""
                hp_text = hp.get("text", "")
                lines.append(f"- {item['name']} ({cid}): ヒロパ「{hp['name']}」{hp_cost}{hp_text}")
            else:
                lines.append(f"- {item['name']} ({cid})")
        lines.append("")

    if minions_cat:
        lines.append("### ミニオン")
        for cid, item in sorted(minions_cat, key=lambda x: (x[1].get("tier") or 99, x[1]["name"], cid)):
            tier_s = f"★{item['tier']} " if item.get("tier") is not None else ""
            gold_s = "[金]" if cid.endswith("_G") or item.get("golden") else ""
            tribes_s = f"[{'/'.join(item['tribes'])}] " if item.get("tribes") else ""
            stat_s = f"{item['atk']}/{item['hp']} " if "atk" in item and "hp" in item else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {tier_s}{gold_s}{item['name']} {tribes_s}{stat_s}({cid}){text_s}")
        lines.append("")

    if spells_cat:
        lines.append("### 酒場の呪文")
        for cid, item in sorted(spells_cat, key=lambda x: (x[1].get("tier") or 99, x[1]["name"], cid)):
            tier_s = f"★{item['tier']} " if item.get("tier") is not None else ""
            cost_s = f"{item['cost']}G, " if item.get("cost") is not None else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {tier_s}{item['name']} ({cost_s}{cid}){text_s}")
        lines.append("")

    if trinkets_cat:
        lines.append("### 装飾品")
        for cid, item in sorted(trinkets_cat, key=lambda x: (x[1]["name"], cid)):
            cost_s = f"{item['cost']}G, " if item.get("cost") is not None else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {item['name']} ({cost_s}{cid}){text_s}")
        lines.append("")

    if others_cat:
        lines.append("### その他カード")
        for cid, item in sorted(others_cat, key=lambda x: (x[1]["name"], cid)):
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {item['name']} ({cid}){text_s}")
        lines.append("")

    if used_dg_ids:
        lines.append("### 悪夢の恵み")
        seen_dg = set()
        for dg_cid in sorted(used_dg_ids):
            name, desc = dark_gift_db.get(dg_cid, (dg_cid, ""))
            if (name, desc) in seen_dg:
                continue
            seen_dg.add((name, desc))
            lines.append(f"- ✦ {name}: {desc}" if desc else f"- ✦ {name}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def build_split_output_path(base_output, game_idx):
    """分割出力時のファイルパス（例: bg_review_rolls_game1.html）を生成する"""
    root, ext = os.path.splitext(base_output)
    if not ext:
        ext = ".html"
    return f"{root}_game{game_idx}{ext}"


def build_ai_output_path(base_output, game_idx=None, ai_only=False):
    """AI専用テキストの出力パス（例: bg_review_rolls_ai.md / bg_review_rolls_game1_ai.md）を生成する"""
    root, ext = os.path.splitext(base_output)
    if ai_only and ext.lower() in (".md", ".txt"):
        if game_idx is not None:
            return f"{root}_game{game_idx}{ext}"
        return base_output
    if game_idx is not None:
        return f"{root}_game{game_idx}_ai.md"
    return f"{root}_ai.md"


def main():
    parser = argparse.ArgumentParser(
        description="Hearthstone Power.log からバトルグラウンド振り返りHTML・AI分析用テキストを生成します。"
    )
    parser.add_argument(
        "log_file",
        nargs="?",
        default=None,
        help="解析対象の Power.log パス（省略時は自動検出）",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="bg_review_rolls.html",
        help="出力ベースファイル名（デフォルト: bg_review_rolls.html）",
    )
    parser.add_argument(
        "-s",
        "--split",
        action="store_true",
        help="試合ごとに個別ファイルへ分割出力する（HTML・AIテキスト両方に適用）",
    )
    parser.add_argument(
        "-g",
        "--game",
        type=int,
        nargs="+",
        default=None,
        help="出力する試合番号を指定（1始まり、複数指定可。例: --game 1 3）",
    )
    parser.add_argument(
        "-a",
        "--ai-text",
        action="store_true",
        help="HTMLに加えて、AI読み込み専用の超軽量Markdown（*_ai.md）も出力する",
    )
    parser.add_argument(
        "--ai-only",
        action="store_true",
        help="HTMLは生成せず、AI読み込み専用の超軽量Markdown（*_ai.md）のみ出力する",
    )
    args = parser.parse_args()

    emit_ai = args.ai_text or args.ai_only
    emit_html = not args.ai_only

    log_file = args.log_file or find_latest_power_log()
    if (not log_file or not os.path.exists(log_file)) and os.path.exists("Power.log"):
        log_file = "Power.log"
    if not log_file or not os.path.exists(log_file):
        print("Power.log が見つかりませんでした。引数にファイルパスを指定してください。")
        sys.exit(1)

    print(f"解析中: {log_file}")
    parsed_games = parse_power_log(log_file)
    if not parsed_games:
        print("バトルグラウンドの試合が見つかりませんでした。")
        sys.exit(1)

    target_pairs = list(enumerate(parsed_games, start=1))
    if args.game:
        wanted = set(args.game)
        target_pairs = [(idx, g) for idx, g in target_pairs if idx in wanted]
        if not target_pairs:
            print(f"指定された試合番号 {args.game} は存在しません（全 {len(parsed_games)} 試合）。")
            sys.exit(1)

    card_catalog = fetch_card_catalog()

    if args.split:
        for game_idx, game in target_pairs:
            place = game.get("final_place")
            place_str = f"{place}位・" if place is not None else ""
            turns_n = len(game["turns"])
            if emit_html:
                out_path = build_split_output_path(args.output, game_idx)
                generate_html([game], out_path, card_catalog=card_catalog, game_numbers=[game_idx])
                size_kb = os.path.getsize(out_path) / 1024
                print(f"HTML出力完了: {os.path.abspath(out_path)} （第 {game_idx} 試合 / {place_str}{turns_n}T / {size_kb:.1f} KB）")
            if emit_ai:
                ai_path = build_ai_output_path(args.output, game_idx=game_idx, ai_only=args.ai_only)
                generate_ai_text([game], ai_path, card_catalog=card_catalog, game_numbers=[game_idx])
                size_kb = os.path.getsize(ai_path) / 1024
                print(f"AIテキスト出力完了: {os.path.abspath(ai_path)} （第 {game_idx} 試合 / {place_str}{turns_n}T / {size_kb:.1f} KB）")
    else:
        game_nums = [idx for idx, _ in target_pairs]
        games_to_write = [g for _, g in target_pairs]
        if emit_html:
            generate_html(games_to_write, args.output, card_catalog=card_catalog, game_numbers=game_nums)
            size_kb = os.path.getsize(args.output) / 1024
            print(f"HTML出力完了: {os.path.abspath(args.output)} （{len(games_to_write)} / 全 {len(parsed_games)} 試合 / {size_kb:.1f} KB）")
        if emit_ai:
            ai_path = build_ai_output_path(args.output, game_idx=None, ai_only=args.ai_only)
            generate_ai_text(games_to_write, ai_path, card_catalog=card_catalog, game_numbers=game_nums)
            size_kb = os.path.getsize(ai_path) / 1024
            print(f"AIテキスト出力完了: {os.path.abspath(ai_path)} （{len(games_to_write)} / 全 {len(parsed_games)} 試合 / {size_kb:.1f} KB）")


if __name__ == "__main__":
    main()
