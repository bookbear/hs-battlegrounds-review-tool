import argparse
import glob
import gzip
import html
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request


# HearthstoneJSON カードマスタのローカルキャッシュ設定
CATALOG_CACHE_VERSION = 1
CATALOG_CACHE_TTL_SECONDS = 24 * 60 * 60

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
SUPPORTED_LANGS = ("ja", "en")
LANG_LOCALE_MAP = {
    "ja": "jaJP",
    "en": "enUS",
}

BG_TRIBE_LABELS_BY_LANG = {
    "ja": {
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
    },
    "en": {
        "ABERRATION": "Aberration",
        "UNDEAD": "Undead",
        "ELEMENTALS": "Elemental",
        "QUILLBOAR": "Quilboar",
        "DRAGON": "Dragon",
        "MURLOC": "Murloc",
        "MECH": "Mech",
        "DEMON": "Demon",
        "PIRATE": "Pirate",
        "BEAST": "Beast",
        "NAGA": "Naga",
    },
}
BG_TRIBE_LABELS = BG_TRIBE_LABELS_BY_LANG["ja"]

# HearthstoneJSON cards.json の race / races 表記用ラベル
CARD_RACE_LABELS_BY_LANG = {
    "ja": {
        **BG_TRIBE_LABELS_BY_LANG["ja"],
        "ALL": "すべて",
        "ELEMENTAL": "エレメンタル",
        "MECHANICAL": "メカ",
        "QUILBOAR": "キルボア",
    },
    "en": {
        **BG_TRIBE_LABELS_BY_LANG["en"],
        "ALL": "All",
        "ELEMENTAL": "Elemental",
        "MECHANICAL": "Mech",
        "QUILBOAR": "Quilboar",
    },
}

DISCOVER_SOURCE_LABELS_BY_LANG = {
    "ja": {
        "TB_BaconShop_Triples_01": "トリプル報酬",
        "BG30_Trinket_1st": "下級装飾品",
        "BG30_Trinket_2nd": "上級装飾品",
    },
    "en": {
        "TB_BaconShop_Triples_01": "Triple Reward",
        "BG30_Trinket_1st": "Lesser Trinket",
        "BG30_Trinket_2nd": "Greater Trinket",
    },
}

I18N = {
    "ja": {
        "unknown": "不明",
        "none": "なし",
        "discover_default": "発見",
        "trinket_lesser": "下級",
        "trinket_greater": "上級",
        "tribe_sep": "・",
        "kw_golden": "ゴールデン",
        "kw_taunt": "挑発",
        "kw_ds": "聖盾",
        "kw_reborn": "蘇り",
        "kw_poison": "猛毒",
        "kw_venom": "毒袋",
        "kw_wf": "疾風",
        "gold_title": "所持金 {num}",
        "tier_cost_title": "ターン開始時の酒場グレードアップ必要コイン数",
        "tier_cost_label": "開始時UP費用",
        "tier_label": "酒場グレード",
        "tier_val": "開始 ★{start} → 終了 ★{end}",
        "place_prefix": "最終順位: ",
        "place_incomplete_suffix": "（途中終了）",
        "page_title_single": "バトルグラウンド振り返りログ（第{game_idx}試合）",
        "page_title_multi": "バトルグラウンド振り返りログ（リロール別）",
        "nav_aria": "試合ナビゲーション",
        "nav_label": "移動:",
        "nav_toc": "目次",
        "nav_place_prefix": "{place}・",
        "nav_game_pill": "第 {game_idx} 試合（{place_str}{turns}T）",
        "h1_title": "バトルグラウンド 振り返りレポート",
        "toc_title_single": "目次（第 {game_idx} 試合）",
        "toc_title_multi": "目次（全 {count} 試合）",
        "toc_dg_summary": " / 恵み {count}回",
        "toc_ban_summary": " / BAN: {names}",
        "game_heading": "第 {game_idx} 試合",
        "toc_game_meta": "全 {turns} ターン / 最大 ★{max_tier}{dg}{ban}",
        "toc_turn_title": "第{game_idx}試合 ターン{turn}（★{t_start}→★{t_end}）",
        "back_to_toc": "↑ 目次へ",
        "timing_before_reroll": "リロール前",
        "timing_after_reroll": "{n}回目リロール後",
        "gold_on_discover": "発見時",
        "dg_header": "✦ 悪夢の恵み（発見・{timing}）",
        "badge_chosen": "選択",
        "discover_header": "🔎 発見：{src}（{timing}）",
        "active_tribes_complete": "出現種族（{cnt}）",
        "active_tribes_partial": "確認できた種族（{cnt}/5）",
        "banned_tribes_complete": "BAN種族（{cnt}）",
        "banned_tribes_partial": "未出現 / BAN候補（{cnt}）",
        "tribe_note_complete": "※ Power.log にはBAN一覧が直接記録されないため、試合中に出現した単一種族ミニオンから推定しています",
        "tribe_note_partial": "※ 早期終了のため全5種族はログ未出現（出現した単一種族ミニオンから推定）",
        "tribe_section_title": "種族プール / BAN情報",
        "hero_choices_title": "試合開始時のヒーロー選択肢",
        "badge_reroll_from": "リロール前",
        "badge_locked": "ロック",
        "gold_start_label": "開始時",
        "reroll_meta": "リロール: {cnt}回",
        "life_header_title": "ターン開始時の残りライフ（体力+装甲）",
        "life_label": "自ライフ",
        "opp_preview_title": "このターンの対戦相手と酒場グレード推移",
        "turn_heading": "ターン {turn}",
        "roll_initial": "リロール前（初期提示）",
        "roll_nth": "{n}回目リロール後",
        "gold_at_roll": "ロール時",
        "gold_after_action": "行動後",
        "shop_lineup": "酒場のラインナップ",
        "badge_frozen": "凍結継続",
        "bought_in_roll": "このロールで購入",
        "badge_bought": "購入",
        "no_purchases": "購入なし",
        "gold_end_label": "残金",
        "hp_changed_badge": "変更",
        "hp_inline_label": "ヒロパ",
        "side_me": "自分",
        "side_opp": "相手",
        "fallback_me": "自分",
        "fallback_opp": "対戦相手",
        "ghost": "ゴースト",
        "chip_place": "順位 {place}",
        "chip_tier": "グレード ★{start} → ★{end}{up}",
        "chip_hp": "体力 {life}",
        "chip_triples": "トリプル {n}回",
        "my_board_label": "自分の盤面（{n}体）",
        "no_minions": "ミニオンなし",
        "my_hand_label": "自分の手札（{n}枚）",
        "no_hand": "手札なし",
        "lb_summary": "ロビー全員の状況（全{n}人：順位・開始/終了グレード・体力・トリプル・装飾品）",
        "lb_col_place": "順位",
        "lb_col_hero": "ヒーロー",
        "lb_col_tier": "酒場グレード",
        "lb_col_hp": "体力 / 装甲",
        "lb_col_triples": "トリプル",
        "lb_col_trinkets": "装飾品",
        "lb_tag_me": "自分",
        "lb_tag_opp": "対戦相手",
        "lb_triples_val": "{n}回",
        "combat_win": "勝利 (+{dmg})",
        "combat_loss": "敗北 (-{dmg})",
        "combat_tie": "引き分け",
        "combat_header": "⚔ 戦闘結果・対戦相手",
        "opp_board_label": "相手の盤面（{n}体）",
        "end_turn_header": "ターン終了時の状況",
        "modal_close_aria": "閉じる",
        "modal_hint": "背景クリック または Esc キーで閉じる",
        "ai_doc_title": "# バトルグラウンド振り返りログ（AI分析用）",
        "ai_dead": "脱落",
        "ai_gold_tag": "[金]",
        "ai_chosen_tag": "[選択]",
        "ai_locked_tag": "[ロック]",
        "ai_frozen_tag": "[凍結]",
        "ai_changed_tag": "[変更]",
        "ai_role_me": "[自]",
        "ai_role_opp": "[敵]",
        "ai_place_known": "最終順位: {place}{suffix}",
        "ai_place_unknown": "最終順位: 不明",
        "ai_game_header": "## 第 {game_idx} 試合｜{hero}｜{place}（全{turns}ターン / 最大★{max_tier}）",
        "ai_active_tribes_complete": "出現種族({cnt})",
        "ai_active_tribes_partial": "確認できた種族({cnt}/5)",
        "ai_banned_tribes_complete": "BAN種族({cnt})",
        "ai_banned_tribes_partial": "未出現/BAN候補({cnt})",
        "ai_tribes_line": "- {active_lbl}: {active_str} ｜ {ban_lbl}: {ban_str}",
        "ai_hero_rerolled_from": " ←リロール前:{prev}",
        "ai_hero_choices_line": "- ヒーロー選択肢: {choices}",
        "ai_up_cost": "UP費{cost}",
        "ai_up_cost_max": "UP費MAX",
        "ai_turn_header": "### T{turn}｜★{t_start}→★{t_end}{up_mark} ({up_cost})｜開始金 {gold}｜自ライフ {life}｜{opp}｜リロール {rerolls}回",
        "ai_timing_before_reroll": "リロール前",
        "ai_timing_after_reroll": "R{n}後",
        "ai_dg_line": "- 悪夢の恵み({timing}, 金{gold}): {opts}",
        "ai_discover_line": "- 発見({src}, {timing}, 金{gold}): {opts}",
        "ai_roll_initial": "R0(初期)",
        "ai_roll_line": "- {r_lbl} ({gold}) 酒場: {shop} ｜ 購入: {bought}",
        "ai_lobby_line": "- ロビー: {items}",
        "ai_opp_triples": "トリプル{n}",
        "ai_opp_hp_prefix": "ヒロパ:",
        "ai_opp_info": " ｜ 相手: {parts}",
        "ai_combat_win": "勝利(+{dmg})",
        "ai_combat_loss": "敗北(-{dmg})",
        "ai_combat_tie": "引き分け",
        "ai_combat_line": "- 戦闘: {res} ｜ 自ライフ {life}{opp_info}",
        "ai_opp_board_line": "  - 相手盤面(左→右,{n}体): {board}",
        "ai_my_hp_line": "  - 自分ヒロパ: {hp}",
        "ai_my_board_line": "  - 自分盤面(終了時★{tier}, 残金{gold}, 左→右,{n}体): {board}",
        "ai_hand_line": "  - 手札({n}枚): {hand}",
        "ai_end_turn_board_line": "- 終了時(★{tier}, 残金{gold}) 盤面(左→右,{n}体): {board}",
        "ai_catalog_title": "## 登場カード辞書（このログに出現したカードのみ）",
        "ai_cat_heroes": "### ヒーロー・ヒーローパワー",
        "ai_cat_hero_with_hp": "- {name} ({cid}): ヒロパ「{hp_name}」{hp_cost}{hp_text}",
        "ai_cat_minions": "### ミニオン",
        "ai_cat_spells": "### 酒場の呪文",
        "ai_cat_trinkets": "### 装飾品",
        "ai_cat_hero_powers": "### ヒーローパワー",
        "ai_cat_others": "### その他カード",
        "ai_cat_dark_gifts": "### 悪夢の恵み",
    },
    "en": {
        "unknown": "Unknown",
        "none": "None",
        "discover_default": "Discover",
        "trinket_lesser": "Lesser",
        "trinket_greater": "Greater",
        "tribe_sep": ", ",
        "kw_golden": "Golden",
        "kw_taunt": "Taunt",
        "kw_ds": "Divine Shield",
        "kw_reborn": "Reborn",
        "kw_poison": "Poisonous",
        "kw_venom": "Venomous",
        "kw_wf": "Windfury",
        "gold_title": "Gold {num}",
        "tier_cost_title": "Tavern upgrade cost at start of turn",
        "tier_cost_label": "Start Upgrade Cost",
        "tier_label": "Tavern Tier",
        "tier_val": "Start ★{start} → End ★{end}",
        "place_prefix": "Final Place: ",
        "place_incomplete_suffix": " (Incomplete)",
        "page_title_single": "Battlegrounds Review Log (Game {game_idx})",
        "page_title_multi": "Battlegrounds Review Log (By Reroll)",
        "nav_aria": "Game navigation",
        "nav_label": "Jump to:",
        "nav_toc": "Contents",
        "nav_place_prefix": "{place} · ",
        "nav_game_pill": "Game {game_idx} ({place_str}{turns}T)",
        "h1_title": "Battlegrounds Review Report",
        "toc_title_single": "Table of Contents (Game {game_idx})",
        "toc_title_multi": "Table of Contents ({count} Games)",
        "toc_dg_summary": " / Dark Gifts: {count}",
        "toc_ban_summary": " / Banned: {names}",
        "game_heading": "Game {game_idx}",
        "toc_game_meta": "{turns} Turns / Max ★{max_tier}{dg}{ban}",
        "toc_turn_title": "Game {game_idx} Turn {turn} (★{t_start}→★{t_end})",
        "back_to_toc": "↑ Top",
        "timing_before_reroll": "Before Reroll",
        "timing_after_reroll": "After Reroll #{n}",
        "gold_on_discover": "On Discover",
        "dg_header": "✦ Dark Gift (Discover · {timing})",
        "badge_chosen": "Picked",
        "discover_header": "🔎 Discover: {src} ({timing})",
        "active_tribes_complete": "Active Tribes ({cnt})",
        "active_tribes_partial": "Observed Tribes ({cnt}/5)",
        "banned_tribes_complete": "Banned Tribes ({cnt})",
        "banned_tribes_partial": "Unseen / Possible Bans ({cnt})",
        "tribe_note_complete": "* Power.log does not record banned tribes directly; inferred from single-tribe pool minions seen during the game.",
        "tribe_note_partial": "* Game ended early before all 5 tribes appeared in the log (inferred from observed single-tribe minions).",
        "tribe_section_title": "Tribe Pool / Bans",
        "hero_choices_title": "Starting Hero Choices",
        "badge_reroll_from": "Before Reroll",
        "badge_locked": "Locked",
        "gold_start_label": "Start",
        "reroll_meta": "Rerolls: {cnt}",
        "life_header_title": "Remaining life at start of turn (Health + Armor)",
        "life_label": "Life",
        "opp_preview_title": "This turn's opponent and Tavern Tier progression",
        "turn_heading": "Turn {turn}",
        "roll_initial": "Initial Shop (Before Reroll)",
        "roll_nth": "After Reroll #{n}",
        "gold_at_roll": "At Roll",
        "gold_after_action": "After Actions",
        "shop_lineup": "Tavern Offerings",
        "badge_frozen": "Frozen",
        "bought_in_roll": "Bought This Roll",
        "badge_bought": "Bought",
        "no_purchases": "None",
        "gold_end_label": "Left",
        "hp_changed_badge": "Changed",
        "hp_inline_label": "Hero Power",
        "side_me": "You",
        "side_opp": "Opp",
        "fallback_me": "You",
        "fallback_opp": "Opponent",
        "ghost": "Ghost",
        "chip_place": "Place {place}",
        "chip_tier": "Tier ★{start} → ★{end}{up}",
        "chip_hp": "Health {life}",
        "chip_triples": "Triples: {n}",
        "my_board_label": "Your Board ({n})",
        "no_minions": "No minions",
        "my_hand_label": "Your Hand ({n})",
        "no_hand": "Empty hand",
        "lb_summary": "Lobby Standings ({n} players: Place, Start/End Tier, Health, Triples, Trinkets)",
        "lb_col_place": "Place",
        "lb_col_hero": "Hero",
        "lb_col_tier": "Tavern Tier",
        "lb_col_hp": "Health / Armor",
        "lb_col_triples": "Triples",
        "lb_col_trinkets": "Trinkets",
        "lb_tag_me": "You",
        "lb_tag_opp": "Opponent",
        "lb_triples_val": "{n}",
        "combat_win": "Win (+{dmg})",
        "combat_loss": "Loss (-{dmg})",
        "combat_tie": "Tie",
        "combat_header": "⚔ Combat Result & Opponent",
        "opp_board_label": "Opponent's Board ({n})",
        "end_turn_header": "End of Turn State",
        "modal_close_aria": "Close",
        "modal_hint": "Click backdrop or press Esc to close",
        "ai_doc_title": "# Battlegrounds Review Log (for AI Analysis)",
        "ai_dead": "Dead",
        "ai_gold_tag": "[Gold]",
        "ai_chosen_tag": "[Picked]",
        "ai_locked_tag": "[Locked]",
        "ai_frozen_tag": "[Frozen]",
        "ai_changed_tag": "[Changed]",
        "ai_role_me": "[Me]",
        "ai_role_opp": "[Opp]",
        "ai_place_known": "Final Place: {place}{suffix}",
        "ai_place_unknown": "Final Place: Unknown",
        "ai_game_header": "## Game {game_idx} | {hero} | {place} ({turns} Turns / Max ★{max_tier})",
        "ai_active_tribes_complete": "Active Tribes({cnt})",
        "ai_active_tribes_partial": "Observed Tribes({cnt}/5)",
        "ai_banned_tribes_complete": "Banned Tribes({cnt})",
        "ai_banned_tribes_partial": "Unseen/Possible Bans({cnt})",
        "ai_tribes_line": "- {active_lbl}: {active_str} | {ban_lbl}: {ban_str}",
        "ai_hero_rerolled_from": " <- Before Reroll: {prev}",
        "ai_hero_choices_line": "- Hero Choices: {choices}",
        "ai_up_cost": "Upgrade {cost}G",
        "ai_up_cost_max": "Upgrade MAX",
        "ai_turn_header": "### T{turn} | ★{t_start}→★{t_end}{up_mark} ({up_cost}) | Start Gold {gold} | Life {life} | {opp} | Rerolls {rerolls}",
        "ai_timing_before_reroll": "Before Reroll",
        "ai_timing_after_reroll": "After R{n}",
        "ai_dg_line": "- Dark Gift ({timing}, Gold {gold}): {opts}",
        "ai_discover_line": "- Discover ({src}, {timing}, Gold {gold}): {opts}",
        "ai_roll_initial": "R0(Init)",
        "ai_roll_line": "- {r_lbl} ({gold}) Shop: {shop} | Bought: {bought}",
        "ai_lobby_line": "- Lobby: {items}",
        "ai_opp_triples": "Triples:{n}",
        "ai_opp_hp_prefix": "HeroPower:",
        "ai_opp_info": " | Opp: {parts}",
        "ai_combat_win": "Win(+{dmg})",
        "ai_combat_loss": "Loss(-{dmg})",
        "ai_combat_tie": "Tie",
        "ai_combat_line": "- Combat: {res} | Life {life}{opp_info}",
        "ai_opp_board_line": "  - Opp Board (L→R, {n}): {board}",
        "ai_my_hp_line": "  - My Hero Power: {hp}",
        "ai_my_board_line": "  - My Board (End ★{tier}, Gold Left {gold}, L→R, {n}): {board}",
        "ai_hand_line": "  - Hand ({n}): {hand}",
        "ai_end_turn_board_line": "- End of Turn (★{tier}, Gold Left {gold}) Board (L→R, {n}): {board}",
        "ai_catalog_title": "## Card Glossary (Cards Appearing in This Log Only)",
        "ai_cat_heroes": "### Heroes & Hero Powers",
        "ai_cat_hero_with_hp": "- {name} ({cid}): Hero Power \"{hp_name}\" {hp_cost}{hp_text}",
        "ai_cat_minions": "### Minions",
        "ai_cat_spells": "### Tavern Spells",
        "ai_cat_trinkets": "### Trinkets",
        "ai_cat_hero_powers": "### Hero Powers",
        "ai_cat_others": "### Other Cards",
        "ai_cat_dark_gifts": "### Dark Gifts",
    },
}


def normalize_lang(lang):
    """言語コードを対応言語（ja / en）へ正規化する"""
    if lang and lang.lower() in SUPPORTED_LANGS:
        return lang.lower()
    return "ja"


def get_hs_locale(lang):
    """言語コードに対応する HearthstoneJSON ロケール名を返す"""
    return LANG_LOCALE_MAP.get(normalize_lang(lang), "jaJP")


def format_place(place, lang="ja"):
    """順位を言語ごとの表記（1位 / 1st 等）へ整形する"""
    if normalize_lang(lang) == "en":
        if 11 <= (place % 100) <= 13:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(place % 10, "th")
        return f"{place}{suffix}"
    return f"{place}位"


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


def clean_card_text(raw_text, lang="ja"):
    """HearthstoneJSON のカードテキストから制御文字・HTMLタグ・テンプレート表記を整形する"""
    if not raw_text:
        return ""
    lang = normalize_lang(lang)
    text = raw_text.replace("[x]", "").replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    if lang == "ja":
        text = re.sub(r"\s*\n+\s*", "", text)
        text = re.sub(r"（0[回枚]?）$", "", text).strip()
    else:
        text = re.sub(r"\s*\n+\s*", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s*\(0\)$", "", text).strip()
    return text


def safe_int(value, default=0):
    """整数文字列を安全に int へ変換する（変換不能時は default を返す）"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_int_or_none(value):
    """整数文字列を安全に int へ変換する（変換不能時は None を返す）"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ensure_parent_dir(file_path):
    """出力ファイルの親ディレクトリが存在しない場合は自動作成する"""
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def lookup_card_entry(card_id, by_card_id):
    """CardID（ゴールデン _G を含む）からカタログエントリを解決する"""
    if not card_id:
        return None
    info = by_card_id.get(card_id)
    if info:
        return info
    if card_id.endswith("_G"):
        return by_card_id.get(card_id[:-2])
    return None


def lookup_card_name(card_id, by_card_id, fallback_name=""):
    """CardID から指定言語のカード名を解決し、未登録時のみフォールバック名を返す"""
    info = lookup_card_entry(card_id, by_card_id)
    if info and info.get("name"):
        return info["name"]
    return fallback_name or card_id or ""


def lookup_hero_name(entry, by_card_id, unknown_label, used_card_ids=None):
    """ヒーローエントリから指定言語のヒーロー名を解決する（カタログ優先・ログ名はフォールバック）"""
    if not entry:
        return unknown_label
    cid = entry.get("card_id", "")
    if cid:
        if used_card_ids is not None:
            used_card_ids.add(cid)
        info = lookup_card_entry(cid, by_card_id)
        if info and info.get("name"):
            return info["name"]
    if entry.get("name"):
        return entry["name"]
    return cid or unknown_label


def lookup_discover_source(disc_ev, discover_source_labels, by_card_id, default_label, used_card_ids=None):
    """発見イベントのソースカード名を指定言語で解決する（ゴールデン _G 対応）"""
    src_cid = disc_ev.get("source_cid", "")
    if src_cid in discover_source_labels:
        return discover_source_labels[src_cid]
    if src_cid:
        info = lookup_card_entry(src_cid, by_card_id)
        if info and info.get("name"):
            if used_card_ids is not None:
                used_card_ids.add(src_cid)
            return info["name"]
    if disc_ev.get("source_name"):
        return disc_ev["source_name"]
    return src_cid or default_label


def group_choice_events_by_roll(turn_data):
    """ターン内の悪夢の恵み・発見イベントを roll_index ごとに時系列順でまとめる"""
    events_by_roll = {}
    for dg_ev in turn_data.get("dark_gifts", []):
        events_by_roll.setdefault(dg_ev["roll_index"], []).append(("dg", dg_ev))
    for disc_ev in turn_data.get("discovers", []):
        events_by_roll.setdefault(disc_ev["roll_index"], []).append(("discover", disc_ev))
    for ev_list in events_by_roll.values():
        ev_list.sort(key=lambda item: item[1].get("seq", 0))
    return events_by_roll


def get_default_cache_dir():
    """カードマスタキャッシュの保存先ディレクトリを返す"""
    env_dir = os.environ.get("BG_REVIEW_CACHE_DIR")
    if env_dir:
        return os.path.expanduser(env_dir)
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return os.path.join(local_app_data, "bg_review", "cache")
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return os.path.join(os.path.expanduser(xdg_cache), "bg_review")
    return os.path.join(os.path.expanduser("~"), ".cache", "bg_review")


def _build_catalog_from_cards(cards, lang="ja"):
    """HearthstoneJSON のカード配列から内部カタログ構造を構築する"""
    lang = normalize_lang(lang)
    race_labels = CARD_RACE_LABELS_BY_LANG[lang]
    catalog = {"dark_gifts": {}, "by_dbf_id": {}, "by_card_id": {}}
    for c in cards:
        cid = c.get("id", "")
        dbf_id = c.get("dbfId")
        name = c.get("name", "")
        text = clean_card_text(c.get("text", ""), lang=lang)
        ctype = c.get("type", "")
        raw_races = c.get("races") or ([c["race"]] if c.get("race") else [])
        tribes = [race_labels.get(r, r) for r in raw_races if r]
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
            dbf_int = safe_int_or_none(dbf_id)
            if dbf_int is not None:
                catalog["by_dbf_id"][dbf_int] = entry
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
            text = clean_card_text(c.get("text", ""), lang=lang)
            dg_db[norm] = (name, text)
    return catalog


def _load_catalog_cache(cache_path):
    """ローカルキャッシュファイルから (catalog, meta) を読み込む（失敗時は (None, None)）"""
    if not cache_path or not os.path.exists(cache_path):
        return None, None
    try:
        with gzip.open(cache_path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict) or payload.get("version") != CATALOG_CACHE_VERSION:
            return None, None
        raw_cat = payload.get("catalog")
        if not isinstance(raw_cat, dict):
            return None, None
        catalog = {
            "dark_gifts": {
                k: (v[0], v[1])
                for k, v in raw_cat.get("dark_gifts", {}).items()
                if isinstance(v, list) and len(v) >= 2
            },
            "by_dbf_id": {
                int(k): v
                for k, v in raw_cat.get("by_dbf_id", {}).items()
                if safe_int_or_none(k) is not None
            },
            "by_card_id": dict(raw_cat.get("by_card_id", {})),
        }
        meta = {
            "fetched_at": float(payload.get("fetched_at", 0.0)),
            "etag": payload.get("etag"),
        }
        return catalog, meta
    except Exception:
        return None, None


def _save_catalog_cache(cache_path, catalog, etag=None):
    """構築済みカタログをローカルキャッシュへアトミックに書き出す"""
    if not cache_path:
        return
    tmp_path = None
    try:
        cache_dir = os.path.dirname(os.path.abspath(cache_path))
        os.makedirs(cache_dir, exist_ok=True)
        payload = {
            "version": CATALOG_CACHE_VERSION,
            "fetched_at": time.time(),
            "etag": etag,
            "catalog": {
                "dark_gifts": {k: [v[0], v[1]] for k, v in catalog.get("dark_gifts", {}).items()},
                "by_dbf_id": {str(k): v for k, v in catalog.get("by_dbf_id", {}).items()},
                "by_card_id": catalog.get("by_card_id", {}),
            },
        }
        fd, tmp_path = tempfile.mkstemp(prefix=".bg_review_cache_", suffix=".tmp", dir=cache_dir)
        os.close(fd)
        with gzip.open(tmp_path, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, cache_path)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def fetch_card_catalog(
    lang="ja",
    use_cache=True,
    refresh_cache=False,
    offline=False,
    cache_dir=None,
    cache_ttl=CATALOG_CACHE_TTL_SECONDS,
):
    """HTML/Markdown生成時に HearthstoneJSON からカード・悪夢の恵み・装飾品マスタを一括取得する（ローカルキャッシュ対応）"""
    lang = normalize_lang(lang)
    hs_locale = get_hs_locale(lang)
    url = f"https://api.hearthstonejson.com/v1/latest/{hs_locale}/cards.json"
    empty_catalog = {"dark_gifts": {}, "by_dbf_id": {}, "by_card_id": {}}

    cache_path = None
    cached_catalog = None
    cached_meta = None
    if use_cache:
        resolved_cache_dir = cache_dir if cache_dir is not None else get_default_cache_dir()
        cache_path = os.path.join(resolved_cache_dir, f"cards_catalog_{hs_locale}.json.gz")
        cached_catalog, cached_meta = _load_catalog_cache(cache_path)

    if offline:
        if cached_catalog is not None:
            return cached_catalog
        print("注意: オフラインモードですがローカルキャッシュが見つかりません。CardIDで表示します。")
        return empty_catalog

    if (
        cached_catalog is not None
        and cached_meta is not None
        and not refresh_cache
        and (time.time() - cached_meta["fetched_at"]) < cache_ttl
    ):
        return cached_catalog

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip",
    }
    if cached_catalog is not None and cached_meta and cached_meta.get("etag") and not refresh_cache:
        headers["If-None-Match"] = cached_meta["etag"]

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            cards = json.loads(raw.decode("utf-8"))
            etag = resp.headers.get("ETag")

        catalog = _build_catalog_from_cards(cards, lang=lang)
        if use_cache and cache_path:
            _save_catalog_cache(cache_path, catalog, etag=etag)
        return catalog
    except urllib.error.HTTPError as e:
        if e.code == 304 and cached_catalog is not None:
            if use_cache and cache_path:
                _save_catalog_cache(cache_path, cached_catalog, etag=cached_meta.get("etag"))
            return cached_catalog
        if cached_catalog is not None:
            print(f"警告: HearthstoneJSON の更新取得に失敗しました（{e}）。ローカルキャッシュを使用します。")
            return cached_catalog
        print(f"警告: HearthstoneJSON からカードマスタの取得に失敗しました（{e}）。CardIDで表示します。")
        return empty_catalog
    except Exception as e:
        if cached_catalog is not None:
            print(f"警告: HearthstoneJSON の更新取得に失敗しました（{e}）。ローカルキャッシュを使用します。")
            return cached_catalog
        print(f"警告: HearthstoneJSON からカードマスタの取得に失敗しました（{e}）。CardIDで表示します。")
        return empty_catalog


def find_latest_power_log():
    """環境変数または Windows / macOS の標準インストール先から最新の Power.log を自動検出する"""
    candidate_dirs = []
    env_dir = os.environ.get("HEARTHSTONE_LOG_DIR")
    if env_dir:
        candidate_dirs.append(os.path.expanduser(env_dir))

    if os.name == "nt":
        candidate_dirs.extend([
            r"C:\Program Files (x86)\Hearthstone\Logs",
            r"C:\Program Files\Hearthstone\Logs",
        ])
    elif sys.platform == "darwin":
        candidate_dirs.extend([
            "/Applications/Hearthstone/Logs",
            os.path.expanduser("~/Library/Preferences/Blizzard/Hearthstone/Logs"),
        ])
    else:
        candidate_dirs.extend([
            r"C:\Program Files (x86)\Hearthstone\Logs",
            "/Applications/Hearthstone/Logs",
        ])

    logs = []
    for base_dir in candidate_dirs:
        if not base_dir:
            continue
        logs.extend(glob.glob(os.path.join(base_dir, "Hearthstone_*", "Power.log")))
        direct_log = os.path.join(base_dir, "Power.log")
        if os.path.isfile(direct_log):
            logs.append(direct_log)

    if not logs:
        return None
    return max(logs, key=os.path.getmtime)


def parse_power_log(log_path):
    """実ログ仕様に合わせてターン・リロール別の酒場提示・購入・所持金・恵み・終了時盤面/手札を抽出する"""
    games = []
    current_game = None
    entities = {}
    attached_by_target = {}  # {target_eid: {enchant_eid: None}}
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

    # 悪夢の恵み・発見選択肢追跡用
    pending_choices = {}
    current_choice = None
    current_chosen_id = None
    choice_seq = 0

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
    combat_opp_hero_powers_snap = []
    combat_my_hp_before = None

    re_player = re.compile(r"Player EntityID=(\d+) PlayerID=(\d+) GameAccountId=\[hi=\d+ lo=(\d+)\]")
    re_player_name = re.compile(r"PlayerID=(\d+), PlayerName=(.+)")
    re_game_type = re.compile(r"^GameType=(\S+)")
    re_full_entity = re.compile(r"FULL_ENTITY - (?:Creating|Updating).*?(?:ID=|id=)(\d+).*?CardID=([^\s\]]*)")
    re_show_entity = re.compile(r"SHOW_ENTITY - Updating Entity=(?:\[.*?id=(\d+).*?\]|(\d+))\s+CardID=([^\s\]]*)")
    re_change_entity = re.compile(r"CHANGE_ENTITY - Updating Entity=(?:\[.*?id=(\d+).*?\]|(\d+))\s+CardID=([^\s\]]*)")
    re_tag_change = re.compile(r"TAG_CHANGE Entity=(?:\[.*?id=(\d+).*?\]|(.+?))\s+tag=(\S+)\s+value=(\S+)")
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
            ent["atk"] = safe_int(value, ent["atk"])
        elif tag == "HEALTH":
            ent["health"] = safe_int(value, ent["health"])
        elif tag == "DAMAGE":
            ent["damage"] = safe_int(value, ent["damage"])
        elif tag == "ARMOR":
            ent["armor"] = safe_int(value, ent["armor"])
        elif tag == "COST":
            cost_val = safe_int_or_none(value)
            if cost_val is not None:
                ent["cost"] = cost_val
        elif tag == "ZONE_POSITION":
            ent["zone_pos"] = safe_int(value, ent["zone_pos"])
        elif tag == "FROZEN":
            ent["frozen"] = safe_int(value, ent["frozen"])
        elif tag == "PREMIUM":
            ent["premium"] = safe_int(value, ent["premium"])
        elif tag == "TAUNT":
            ent["taunt"] = safe_int(value, ent["taunt"])
        elif tag == "DIVINE_SHIELD":
            ent["divine_shield"] = safe_int(value, ent["divine_shield"])
        elif tag == "REBORN":
            ent["reborn"] = safe_int(value, ent["reborn"])
        elif tag == "POISONOUS":
            ent["poisonous"] = safe_int(value, ent["poisonous"])
        elif tag == "VENOMOUS":
            ent["venomous"] = safe_int(value, ent["venomous"])
        elif tag == "WINDFURY":
            ent["windfury"] = safe_int(value, ent["windfury"])
        elif tag == "PLAYER_ID":
            ent["player_id"] = value
        elif tag == "PLAYER_TECH_LEVEL":
            ent["tech_level"] = safe_int(value, ent["tech_level"])
        elif tag == "PLAYER_LEADERBOARD_PLACE":
            ent["place"] = safe_int(value, ent["place"])
        elif tag == "PLAYER_TRIPLES":
            ent["triples"] = safe_int(value, ent["triples"])
        elif tag == "BACON_FIRST_TRINKET_DATABASE_ID":
            ent["trinket1"] = safe_int(value, ent["trinket1"])
        elif tag == "BACON_SECOND_TRINKET_DATABASE_ID":
            ent["trinket2"] = safe_int(value, ent["trinket2"])
        elif tag == "TRANSIENT_ENTITY":
            ent["transient"] = safe_int(value, ent["transient"])
        elif tag == "BACON_LOCKED_MULLIGAN_HERO":
            ent["locked_hero"] = safe_int(value, ent["locked_hero"])
        elif tag == "IS_BACON_POOL_MINION":
            ent["is_pool_minion"] = safe_int(value, ent["is_pool_minion"])
        elif tag.startswith("BACON_SUBSET_"):
            sub = tag[len("BACON_SUBSET_"):]
            if value == "1":
                ent["subsets"].add(sub)
        elif tag == "ATTACHED":
            old_target = ent["attached"]
            if old_target and old_target != value:
                old_bucket = attached_by_target.get(old_target)
                if old_bucket is not None:
                    old_bucket.pop(ent["id"], None)
                    if not old_bucket:
                        attached_by_target.pop(old_target, None)
            ent["attached"] = value
            if value and value != "0":
                attached_by_target.setdefault(value, {})[ent["id"]] = None
                if ent["card_id"]:
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
        for other_eid in attached_by_target.get(target_eid, ()):
            other = entities.get(other_eid)
            if other and other["attached"] == target_eid and other["zone"] == "PLAY":
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
                "discovers": [],
                "tier_start": 1,
                "tier_end": 1,
                "upgrade_cost_start": None,
                "gold_start": None,
                "max_gold_start": None,
                "gold_end": None,
                "max_gold_end": None,
                "hero_powers_end": [],
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
                if prev is None or safe_int(e["id"]) > safe_int(prev["id"]):
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
        """戦闘開始時点の相手盤面・相手ヒーロー・相手ヒーローパワーをスナップショットする"""
        nonlocal combat_snap_done, opp_combat_hero_eid, combat_opp_board_snap, combat_opp_hero_snap, combat_opp_hero_powers_snap
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
        opp_hp_ents = [
            e
            for e in entities.values()
            if e["controller"] == bob_pid
            and e["zone"] == "PLAY"
            and e["card_type"] == "HERO_POWER"
            and e["card_id"]
        ]
        opp_board_ents.sort(key=lambda e: e["zone_pos"])
        opp_hp_ents.sort(key=lambda e: (e["zone_pos"], safe_int(e["id"])))
        opp_combat_hero_eid = opp_heroes[0]["id"] if opp_heroes else None
        combat_opp_board_snap = [build_minion_snapshot(e) for e in opp_board_ents]
        combat_opp_hero_powers_snap = [
            {
                "card_id": e["card_id"],
                "name": e["name"],
                "cost": e["cost"],
            }
            for e in opp_hp_ents
        ]
        if opp_heroes:
            oh = opp_heroes[0]
            combat_opp_hero_snap = {
                "card_id": oh["card_id"],
                "name": oh["name"],
                "hp": oh["health"] - oh["damage"],
                "armor": oh["armor"],
                "is_ghost": oh["card_id"] == "TB_BaconShop_HERO_KelThuzad",
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
            "opp_hero_powers": list(combat_opp_hero_powers_snap),
            "opp_is_ghost": bool(combat_opp_hero_snap and combat_opp_hero_snap.get("is_ghost")),
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
        """ターン終了時点の自分のヒーローパワー・盤面ミニオン・手札・残り所持金・リーダーボードを記録する"""
        nonlocal frozen_from_prev_turn, prev_lb_tiers_end
        if not current_game or current_turn <= 0:
            return
        turn_data = get_turn_data(current_turn)
        if turn_data["end_recorded"]:
            return

        # ターン終了時の自分のヒーローパワー（呪文等で変更されることがあるため毎ターン記録）
        hp_ents = [
            e
            for e in entities.values()
            if e["controller"] == my_pid
            and e["zone"] == "PLAY"
            and e["card_type"] == "HERO_POWER"
            and e["card_id"]
        ]
        hp_ents.sort(key=lambda e: (e["zone_pos"], safe_int(e["id"])))
        turn_data["hero_powers_end"] = [
            {
                "card_id": e["card_id"],
                "name": e["name"],
                "cost": e["cost"],
            }
            for e in hp_ents
        ]

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

    def finalize_current_game():
        """試合終了・中断時（次試合開始またはEOF）に未確定の雇用／戦闘フェーズと種族メタを確定する"""
        if not current_game or current_game["is_battlegrounds"] is False:
            return
        if is_recruit_phase and current_turn > 0:
            snapshot_end_of_turn()
        elif (not is_recruit_phase) and current_turn > 0:
            if not combat_snap_done:
                snapshot_combat_start()
            finalize_combat_result()
        finalize_game_meta()

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

            # 選択肢提示（開始時ヒーロー選択・悪夢の恵み・準備フェイズの発見全般）
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
                        "source_name": "",
                        "is_recruit": is_recruit_phase,
                        "turn": current_turn,
                        "roll_index": roll_idx,
                        "gold": current_gold(),
                        "max_gold": current_max_gold(),
                        "options": [],
                        "chosen_eid": None,
                        "chosen_eids": [],
                        "recorded": False,
                        "seq": 0,
                    }
                    if choice_id:
                        pending_choices[choice_id] = current_choice
                elif current_choice and "Source=" in c_line:
                    m_scid = re_ref_card_id.search(c_line)
                    if m_scid:
                        current_choice["source_cid"] = m_scid.group(1)
                    m_sname = re_entity_name.search(c_line)
                    if m_sname:
                        current_choice["source_name"] = m_sname.group(1)
                elif current_choice and "Entities[" in c_line:
                    m_eid = re_choice_id.search(c_line)
                    m_rcid = re_ref_card_id.search(c_line)
                    m_oname = re_entity_name.search(c_line)
                    if m_eid:
                        opt_eid = m_eid.group(1)
                        opt_ent = get_entity(opt_eid)
                        opt_cid = m_rcid.group(1) if m_rcid else opt_ent["card_id"]
                        opt_name = m_oname.group(1) if m_oname else opt_ent["name"]
                        if opt_name and not opt_ent["name"]:
                            opt_ent["name"] = opt_name
                        if opt_cid and not opt_ent["card_history"]:
                            record_card_id(opt_ent, opt_cid)
                        dg_list = collect_dark_gifts_for_entity(opt_ent)
                        current_choice["options"].append(
                            {
                                "eid": opt_eid,
                                "card_id": opt_cid,
                                "name": opt_name,
                                "card_type": opt_ent["card_type"],
                                "golden": bool(opt_ent["premium"] or opt_cid.endswith("_G")),
                                "dark_gifts": dg_list,
                            }
                        )
                continue

            # 選択結果（開始時ヒーロー選択・悪夢の恵み・準備フェイズの発見全般）
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
                        chosen_eid = m_eid.group(1)
                        if chosen_eid not in cb["chosen_eids"]:
                            cb["chosen_eids"].append(chosen_eid)
                        cb["chosen_eid"] = cb["chosen_eids"][0]
                        if not cb["recorded"]:
                            choice_seq += 1
                            cb["seq"] = choice_seq
                            cb["recorded"] = True
                            get_turn_data(cb["turn"])["dark_gifts"].append(cb)
                    elif (
                        m_eid
                        and cb["choice_type"] == "GENERAL"
                        and cb["is_recruit"]
                        and cb["turn"] > 0
                        and any(opt["card_id"] for opt in cb["options"])
                    ):
                        chosen_eid = m_eid.group(1)
                        if chosen_eid not in cb["chosen_eids"]:
                            cb["chosen_eids"].append(chosen_eid)
                        cb["chosen_eid"] = cb["chosen_eids"][0]
                        if not cb["recorded"]:
                            choice_seq += 1
                            cb["seq"] = choice_seq
                            cb["recorded"] = True
                            get_turn_data(cb["turn"])["discovers"].append(cb)
                continue

            if "GameState.DebugPrintPower() - " not in raw_line:
                continue
            line = raw_line.split("GameState.DebugPrintPower() - ", 1)[1].strip()

            if line.startswith("CREATE_GAME"):
                finalize_current_game()
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
                attached_by_target = {}
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
                choice_seq = 0
                in_my_player_block = False
                next_opp_pid = None
                prev_lb_tiers_end = {}
                combat_snap_done = False
                opp_combat_hero_eid = None
                combat_hero_attacker = None
                combat_dmg = 0
                combat_opp_board_snap = []
                combat_opp_hero_snap = None
                combat_opp_hero_powers_snap = []
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
                    dmg_val = safe_int(value, 0)
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
                        if not combat_snap_done:
                            snapshot_combat_start()
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
                            combat_opp_hero_powers_snap = []
                            mh = entities.get(my_hero_eid) if my_hero_eid else None
                            combat_my_hp_before = (mh["health"] - mh["damage"], mh["armor"]) if mh else None
                    elif tag == "TURN" and is_recruit_phase:
                        turn_val = safe_int_or_none(value)
                        if turn_val is not None:
                            current_turn = turn_val
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
                        tier_val = safe_int_or_none(value)
                        if tier_val is not None:
                            get_turn_data(current_turn)["tier_end"] = tier_val
                    elif tag == "RESOURCES":
                        resources = safe_int(value, resources)
                        if is_recruit_phase and current_turn > 0:
                            turn_data = get_turn_data(current_turn)
                            if not turn_data["rolls"]:
                                turn_data["gold_start"] = current_gold()
                                turn_data["max_gold_start"] = current_max_gold()
                            update_current_roll_gold()
                    elif tag == "RESOURCES_USED":
                        resources_used = safe_int(value, resources_used)
                        if is_recruit_phase and current_turn > 0:
                            turn_data = get_turn_data(current_turn)
                            if not turn_data["rolls"]:
                                turn_data["gold_start"] = current_gold()
                                turn_data["max_gold_start"] = current_max_gold()
                            update_current_roll_gold()
                    elif tag == "TEMP_RESOURCES":
                        temp_resources = safe_int(value, temp_resources)
                        update_current_roll_gold()
                    continue

                # 自分のヒーローエンティティの対戦相手ID・最終順位
                if eid and my_hero_eid and eid == my_hero_eid:
                    if tag == "NEXT_OPPONENT_PLAYER_ID":
                        next_opp_pid = value
                        if is_recruit_phase and current_turn > 0:
                            get_turn_data(current_turn)["opp_pid"] = value
                    elif tag == "PLAYER_LEADERBOARD_PLACE":
                        place_val = safe_int(value, 0)
                        if place_val > 0 and current_game["playstate"] != "WON":
                            current_game["final_place"] = place_val

                # 酒場グレードアップの検知（自分のヒーローエンティティ）
                if eid and tag == "PLAYER_TECH_LEVEL" and is_recruit_phase and current_turn > 0:
                    ent = get_entity(eid)
                    if ent["controller"] == my_pid and ent["zone"] == "PLAY":
                        tier_val = safe_int_or_none(value)
                        if tier_val is not None:
                            get_turn_data(current_turn)["tier_end"] = tier_val

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

    finalize_current_game()

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


def generate_html(games, output_path, card_catalog=None, game_numbers=None, lang="ja"):
    """リロールごとの酒場・所持金・グレード・悪夢の恵み・盤面/手札・戦闘結果・ロビー情報をHTML出力する"""
    lang = normalize_lang(lang)
    tr = I18N[lang]
    hs_locale = get_hs_locale(lang)
    tribe_labels = BG_TRIBE_LABELS_BY_LANG[lang]
    discover_source_labels = DISCOVER_SOURCE_LABELS_BY_LANG[lang]
    if card_catalog is None:
        card_catalog = fetch_card_catalog(lang=lang)
    if game_numbers is None:
        game_numbers = list(range(1, len(games) + 1))
    dark_gift_db = card_catalog.get("dark_gifts", {})
    by_dbf_id = card_catalog.get("by_dbf_id", {})
    by_card_id = card_catalog.get("by_card_id", {})
    bgs_base = f"https://art.hearthstonejson.com/v1/bgs/latest/{hs_locale}/256x"
    render_base = f"https://art.hearthstonejson.com/v1/render/latest/{hs_locale}/256x"
    used_card_ids = set()

    def resolve_card_entry(card_id):
        return lookup_card_entry(card_id, by_card_id)

    def resolve_card_name(card_id):
        return lookup_card_name(card_id, by_card_id)

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
        gold_title = html.escape(tr["gold_title"].format(num=num_text))
        return (
            f"<span class='gold-group' title='{gold_title}'>"
            f"{label_html}<span class='coin-tray' data-on='{gold}' data-off='{spent}'></span>"
            f"<span class='gold-num'>{num_text}</span>"
            f"</span>"
        )

    def render_tier_badge(tier_start, tier_end, upgrade_cost_start=None):
        """ターン開始時・終了時の酒場グレードと開始時の昇格必要コイン数を描画する"""
        upgraded = tier_end > tier_start
        cls = "tier-badge tier-up" if upgraded else "tier-badge"
        up_tag = "<span class='tier-up-tag'>UP</span>" if upgraded else ""
        tier_cost_label = html.escape(tr["tier_cost_label"])
        tier_cost_title = html.escape(tr["tier_cost_title"])
        tier_label = html.escape(tr["tier_label"])
        tier_val = html.escape(tr["tier_val"].format(start=tier_start, end=tier_end))
        if upgrade_cost_start is not None:
            cost_html = (
                f"<span class='tier-cost' title='{tier_cost_title}'>"
                f"<span class='tier-label'>{tier_cost_label}</span>"
                f"<svg class='coin-icon' viewBox='0 0 24 24'><use href='#coin-on'/></svg>"
                f"<span class='gold-num'>{upgrade_cost_start}</span>"
                f"</span>"
            )
        else:
            cost_html = (
                f"<span class='tier-cost'>"
                f"<span class='tier-label'>{tier_cost_label}</span>"
                f"<span class='tier-max'>MAX</span>"
                f"</span>"
            )
        return (
            f"<span class='{cls}'>"
            f"<span class='tier-label'>{tier_label}</span>"
            f"<span class='tier-val'>{tier_val}</span>"
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
        prefix = tr["place_prefix"] if show_prefix else ""
        suffix = "" if completed else tr["place_incomplete_suffix"]
        place_text = format_place(place, lang)
        return f"<span class='{cls}'>{icon}{html.escape(prefix)}{html.escape(place_text)}{html.escape(suffix)}</span>"

    def render_minion_badges(m):
        parts = []
        if m["golden"]:
            parts.append(f"<span class='kw-tag kw-gold'>{html.escape(tr['kw_golden'])}</span>")
        if m["taunt"]:
            parts.append(f"<span class='kw-tag kw-taunt'>{html.escape(tr['kw_taunt'])}</span>")
        if m["divine_shield"]:
            parts.append(f"<span class='kw-tag kw-ds'>{html.escape(tr['kw_ds'])}</span>")
        if m["reborn"]:
            parts.append(f"<span class='kw-tag kw-reborn'>{html.escape(tr['kw_reborn'])}</span>")
        if m["poisonous"]:
            parts.append(f"<span class='kw-tag kw-poison'>{html.escape(tr['kw_poison'])}</span>")
        if m["venomous"]:
            parts.append(f"<span class='kw-tag kw-poison'>{html.escape(tr['kw_venom'])}</span>")
        if m["windfury"]:
            parts.append(f"<span class='kw-tag kw-wf'>{html.escape(tr['kw_wf'])}</span>")
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
        return lookup_hero_name(entry, by_card_id, tr["unknown"], used_card_ids=used_card_ids)

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
        dbf_int = safe_int_or_none(dbf_id)
        info = by_dbf_id.get(dbf_int) if dbf_int is not None else None
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
        tr["page_title_single"].format(game_idx=game_numbers[0])
        if is_single_game
        else tr["page_title_multi"]
    )

    html_parts = [
        "<!DOCTYPE html>",
        f"<html lang='{lang}'>",
        "<head>",
        "<meta charset='UTF-8'>",
        f"<title>{html.escape(page_title)}</title>",
        "<style>",
        "  html { --nav-offset: 60px; scroll-behavior: smooth; }",
        "  body { font-family: sans-serif; background: #1a1c23; color: #f0f0f0; padding: 0 20px 20px; margin: 0; }",
        "  h1, h2 { border-bottom: 1px solid #3a3f4b; padding-bottom: 8px; }",
        "  .sticky-nav { position: sticky; top: 0; z-index: 500; background: rgba(20, 22, 30, 0.94); backdrop-filter: blur(6px); border-bottom: 1px solid #343946; margin: 0 -20px 18px; padding: 8px 20px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }",
        "  .sticky-nav-label { font-size: 0.8em; color: #9aa3b2; margin-right: 4px; }",
        "  .nav-pill { display: inline-flex; align-items: center; gap: 5px; padding: 4px 11px; border-radius: 999px; background: #252936; border: 1px solid #3d4457; color: #e6ecf5; text-decoration: none; font-size: 0.85em; font-weight: bold; transition: background 0.12s, border-color 0.12s; }",
        "  .nav-pill:hover { background: #31384b; border-color: #6ca4f2; color: #fff; }",
        "  .nav-pill-toc { background: #2c261a; border-color: #6b5627; color: #ffd75e; }",
        "  .nav-pill-toc:hover { background: #3d3420; border-color: #ffd100; }",
        "  .toc-box { background: #222631; border: 1px solid #383e4e; border-radius: 8px; padding: 14px 16px; margin-bottom: 24px; scroll-margin-top: var(--nav-offset); }",
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
        "  .game-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; scroll-margin-top: var(--nav-offset); }",
        "  .game-header h2 { flex: 1; margin: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }",
        "  .place-badge { display: inline-flex; align-items: center; font-size: 0.72em; font-weight: bold; padding: 3px 10px; border-radius: 999px; vertical-align: middle; }",
        "  .toc-game-name { display: flex; align-items: center; gap: 8px; }",
        "  .toc-game-name .place-badge { font-size: 0.78em; padding: 1px 8px; }",
        "  .place-1st { background: #3b2f0b; border: 1px solid #ffd700; color: #ffe46b; box-shadow: 0 0 8px rgba(255, 215, 0, 0.3); }",
        "  .place-top4 { background: #183325; border: 1px solid #4caf50; color: #9cf0be; }",
        "  .place-bottom { background: #301f24; border: 1px solid #8a434e; color: #f0a8b2; }",
        "  .back-to-toc { font-size: 0.82em; color: #ffd75e; text-decoration: none; padding: 4px 10px; border-radius: 999px; border: 1px solid #594a26; background: #262116; white-space: nowrap; }",
        "  .back-to-toc:hover { background: #38301e; border-color: #ffd100; }",
        "  .hero-img { width: 90px; height: auto; aspect-ratio: 256 / 388; object-fit: contain; overflow: hidden; display: block; border-radius: 6px; }",
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
        "  .turn-box { background: #252832; border-radius: 8px; padding: 16px; margin-bottom: 24px; scroll-margin-top: var(--nav-offset); }",
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
        "  .card-item img { width: 120px; height: auto; aspect-ratio: 256 / 388; object-fit: contain; overflow: hidden; border-radius: 6px; display: block; cursor: zoom-in; transition: transform 0.12s ease; }",
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
        "  .badge-discover-chosen { background: #00acc1; color: #fff; }",
        "  .badge-hp-changed { background: #ef6c00; color: #fff; }",
        "  .dg-block { background: #221d2e; border-left: 4px solid #b25cff; border-radius: 4px; padding: 12px; margin-bottom: 12px; }",
        "  .dg-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-weight: bold; color: #d7a6ff; margin-bottom: 10px; font-size: 0.95em; }",
        "  .dg-option { width: 148px; background: #191623; border: 1px solid #382e4d; border-radius: 8px; padding: 8px; box-sizing: border-box; }",
        "  .dg-option img { width: 130px; margin: 0 auto; }",
        "  .dg-option-chosen { border: 2px solid #b25cff; background: #261c38; box-shadow: 0 0 12px rgba(178, 92, 255, 0.35); }",
        "  .dg-option-unchosen { opacity: 0.72; }",
        "  .discover-block { background: #19242b; border-left: 4px solid #26c6da; border-radius: 4px; padding: 12px; margin-bottom: 12px; }",
        "  .discover-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-weight: bold; color: #7ce8f5; margin-bottom: 10px; font-size: 0.95em; }",
        "  .discover-option { width: 140px; background: #151e24; border: 1px solid #2b444f; border-radius: 8px; padding: 8px; box-sizing: border-box; }",
        "  .discover-option img { width: 122px; margin: 0 auto; }",
        "  .discover-option-chosen { border: 2px solid #26c6da; background: #182b33; box-shadow: 0 0 12px rgba(38, 198, 218, 0.35); }",
        "  .discover-option-unchosen { opacity: 0.72; }",
        "  .discover-opt-name { margin-top: 5px; font-size: 0.74em; color: #d5e8ef; line-height: 1.3; word-break: break-word; }",
        "  .hp-card img { border-radius: 6px; }",
        "  .hp-changed img { outline: 2px solid #ff9800; box-shadow: 0 0 10px rgba(255, 152, 0, 0.45); }",
        "  .hp-changed-pill { display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 4px; background: #ef6c00; color: #fff; font-size: 0.85em; font-weight: bold; }",
        "  .hp-caption { margin-top: 5px; display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 4px; font-size: 0.74em; color: #e2e8f4; line-height: 1.3; }",
        "  .hp-cost-pill { background: #3b3117; border: 1px solid #b58c28; color: #ffd75e; font-weight: bold; padding: 0 5px; border-radius: 4px; font-size: 0.92em; }",
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
        "  .opp-summary-card { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; background: #1b161a; border: 1px solid #3f2d34; border-radius: 6px; padding: 8px 12px; margin-bottom: 10px; }",
        "  .my-summary-card { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; background: #1c1d19; border: 1px solid #544726; border-radius: 6px; padding: 8px 12px; margin-bottom: 10px; }",
        "  .side-tag { font-size: 0.72em; font-weight: bold; padding: 1px 6px; border-radius: 4px; }",
        "  .side-tag-opp { background: #521e27; border: 1px solid #e05263; color: #ffb3bc; }",
        "  .side-tag-me { background: #4d3f12; border: 1px solid #f0b429; color: #ffe57f; }",
        "  .combat-divider { border: none; border-top: 1px dashed #4a3c44; margin: 14px 0 12px; }",
        "  .combat-my-boards { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; }",
        "  .hp-inline-list { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }",
        "  .hp-inline-box { display: inline-flex; align-items: center; gap: 8px; background: #141720; border: 1px solid #3b4257; border-radius: 6px; padding: 5px 10px 5px 6px; max-width: 440px; }",
        "  .hp-inline-changed { border-color: #ff9800; background: #241b12; box-shadow: 0 0 8px rgba(255, 152, 0, 0.28); }",
        "  .hp-inline-thumb { width: 42px; height: auto; aspect-ratio: 256 / 388; object-fit: contain; overflow: hidden; border-radius: 5px; display: block; flex-shrink: 0; }",
        "  .hp-inline-meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }",
        "  .hp-inline-top { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; font-size: 0.8em; }",
        "  .hp-inline-label { color: #8f9bb0; font-size: 0.88em; }",
        "  .hp-inline-name { font-weight: bold; color: #f0f4fa; }",
        "  .hp-inline-desc { font-size: 0.72em; color: #b7c2d4; line-height: 1.35; }",
        "  .opp-hero-thumb { width: 48px; height: 48px; border-radius: 6px; object-fit: cover; display: block; border: 1px solid #5c434d; }",
        "  .my-hero-thumb { width: 48px; height: 48px; border-radius: 6px; object-fit: cover; display: block; border: 1px solid #8a7230; }",
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
        f"const BGS_BASE = 'https://art.hearthstonejson.com/v1/bgs/latest/{hs_locale}/256x';",
        f"const RENDER_BASE = 'https://art.hearthstonejson.com/v1/render/latest/{hs_locale}/256x';",
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
        "function updateNavOffset() {",
        "  const nav = document.querySelector('.sticky-nav');",
        "  if (!nav) return;",
        "  const h = Math.ceil(nav.getBoundingClientRect().height) + 12;",
        "  document.documentElement.style.setProperty('--nav-offset', `${h}px`);",
        "}",
        "document.addEventListener('DOMContentLoaded', function() {",
        "  renderCoinTrays();",
        "  updateNavOffset();",
        "  const nav = document.querySelector('.sticky-nav');",
        "  if (nav && typeof ResizeObserver !== 'undefined') {",
        "    new ResizeObserver(updateNavOffset).observe(nav);",
        "  }",
        "});",
        "window.addEventListener('resize', updateNavOffset);",
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
        f"<nav class='sticky-nav' aria-label='{html.escape(tr['nav_aria'])}'>",
        f"  <span class='sticky-nav-label'>{html.escape(tr['nav_label'])}</span>",
        f"  <a class='nav-pill nav-pill-toc' href='#toc'>{html.escape(tr['nav_toc'])}</a>",
    ]

    for game_idx, game in zip(game_numbers, games):
        turn_count = len(game["turns"])
        place = game.get("final_place")
        place_str = (
            tr["nav_place_prefix"].format(place=format_place(place, lang))
            if place is not None
            else ""
        )
        pill_text = tr["nav_game_pill"].format(
            game_idx=game_idx, place_str=place_str, turns=turn_count
        )
        html_parts.append(
            f"  <a class='nav-pill' href='#game-{game_idx}'>{html.escape(pill_text)}</a>"
        )
    html_parts.append("</nav>")
    html_parts.append(f"<h1>{html.escape(tr['h1_title'])}</h1>")

    # 目次（各試合＋各ターンへのジャンプ）
    toc_title = (
        tr["toc_title_single"].format(game_idx=game_numbers[0])
        if is_single_game
        else tr["toc_title_multi"].format(count=len(games))
    )
    html_parts.append("<div id='toc' class='toc-box'>")
    html_parts.append(f"<div class='toc-title'>{html.escape(toc_title)}</div>")
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
        dg_summary = tr["toc_dg_summary"].format(count=dg_count) if dg_count else ""
        ban_summary = ""
        if len(game["active_tribes"]) >= 5 and game["banned_tribes"]:
            ban_names = tr["tribe_sep"].join(tribe_labels.get(t, t) for t in game["banned_tribes"])
            ban_summary = tr["toc_ban_summary"].format(names=ban_names)
        toc_place_badge = render_place_badge(game, show_prefix=False)
        game_heading_txt = html.escape(tr["game_heading"].format(game_idx=game_idx))
        toc_meta_txt = html.escape(
            tr["toc_game_meta"].format(
                turns=len(sorted_turns),
                max_tier=max_tier,
                dg=dg_summary,
                ban=ban_summary,
            )
        )
        html_parts.append("<div class='toc-game'>")
        html_parts.append(
            f"<a class='toc-game-link' href='#game-{game_idx}'>"
            f"{hero_thumb}"
            f"<span>"
            f"<div class='toc-game-name'><span>{game_heading_txt}</span>{toc_place_badge}</div>"
            f"<div class='toc-game-meta'>{toc_meta_txt}</div>"
            f"</span>"
            f"</a>"
        )
        html_parts.append("<div class='toc-turns'>")
        for t in sorted_turns:
            td = game["turns"][t]
            has_dg = bool(td["dark_gifts"])
            t_cls = "toc-turn-link toc-turn-dg" if has_dg else "toc-turn-link"
            dg_mark = "✦" if has_dg else ""
            turn_title_attr = html.escape(
                tr["toc_turn_title"].format(
                    game_idx=game_idx,
                    turn=t,
                    t_start=td["tier_start"],
                    t_end=td["tier_end"],
                )
            )
            html_parts.append(
                f"<a class='{t_cls}' href='#game-{game_idx}-turn-{t}' title='{turn_title_attr}'>"
                f"T{t}{dg_mark}</a>"
            )
        html_parts.append("</div></div>")
    html_parts.append("</div></div>")

    def resolve_discover_source_label(disc_ev):
        return lookup_discover_source(
            disc_ev,
            discover_source_labels,
            by_card_id,
            tr["discover_default"],
            used_card_ids=used_card_ids,
        )

    def append_dark_gift_block(dg_ev):
        r_idx = dg_ev["roll_index"]
        timing = (
            tr["timing_before_reroll"]
            if r_idx == 0
            else tr["timing_after_reroll"].format(n=r_idx)
        )
        dg_gold_html = render_coins(dg_ev["gold"], dg_ev["max_gold"], label=tr["gold_on_discover"])
        chosen_set = set(
            dg_ev.get("chosen_eids")
            or ([dg_ev["chosen_eid"]] if dg_ev.get("chosen_eid") else [])
        )
        dg_hdr_txt = html.escape(tr["dg_header"].format(timing=timing))
        chosen_badge_txt = html.escape(tr["badge_chosen"])
        html_parts.append("<div class='dg-block'>")
        html_parts.append(
            f"<div class='dg-header'>"
            f"<span>{dg_hdr_txt}</span>"
            f"<span class='roll-gold-bar'>{dg_gold_html}</span>"
            f"</div>"
        )
        html_parts.append("<div class='card-row'>")
        for opt in dg_ev["options"]:
            is_chosen = opt["eid"] in chosen_set
            cls_list = ["card-item", "dg-option"]
            cls_list.append("dg-option-chosen" if is_chosen else "dg-option-unchosen")
            if opt["golden"]:
                cls_list.append("golden")
            badge_html = (
                f"<span class='badge badge-dg-chosen'>{chosen_badge_txt}</span>"
                if is_chosen
                else ""
            )
            html_parts.append(
                f"<div class='{' '.join(cls_list)}'>"
                f"{badge_html}"
                f"{build_img_tag(opt['card_id'])}"
                f"{render_dark_gift_box(opt['dark_gifts'])}"
                f"</div>"
            )
        html_parts.append("</div></div>")

    def append_discover_block(disc_ev):
        r_idx = disc_ev["roll_index"]
        timing = (
            tr["timing_before_reroll"]
            if r_idx == 0
            else tr["timing_after_reroll"].format(n=r_idx)
        )
        src_label = resolve_discover_source_label(disc_ev)
        disc_gold_html = render_coins(
            disc_ev["gold"], disc_ev["max_gold"], label=tr["gold_on_discover"]
        )
        chosen_set = set(
            disc_ev.get("chosen_eids")
            or ([disc_ev["chosen_eid"]] if disc_ev.get("chosen_eid") else [])
        )
        disc_hdr_txt = html.escape(tr["discover_header"].format(src=src_label, timing=timing))
        chosen_badge_txt = html.escape(tr["badge_chosen"])
        html_parts.append("<div class='discover-block'>")
        html_parts.append(
            f"<div class='discover-header'>"
            f"<span>{disc_hdr_txt}</span>"
            f"<span class='roll-gold-bar'>{disc_gold_html}</span>"
            f"</div>"
        )
        html_parts.append("<div class='card-row'>")
        for opt in disc_ev["options"]:
            is_chosen = opt["eid"] in chosen_set
            cls_list = ["card-item", "discover-option"]
            cls_list.append("discover-option-chosen" if is_chosen else "discover-option-unchosen")
            if opt.get("golden"):
                cls_list.append("golden")
            badge_html = (
                f"<span class='badge badge-discover-chosen'>{chosen_badge_txt}</span>"
                if is_chosen
                else ""
            )
            opt_cid = opt.get("card_id", "")
            opt_name = (
                resolve_card_name(opt_cid) if opt_cid else ""
            ) or opt.get("name") or opt_cid
            if opt_cid and opt_name == opt_cid and opt.get("name"):
                opt_name = opt["name"]
            img_html = build_img_tag(opt_cid, alt=opt_name) if opt_cid else ""
            name_html = (
                f"<div class='discover-opt-name'>{html.escape(opt_name)}</div>"
                if opt_name
                else ""
            )
            html_parts.append(
                f"<div class='{' '.join(cls_list)}'>"
                f"{badge_html}"
                f"{img_html}"
                f"{name_html}"
                f"{render_dark_gift_box(opt.get('dark_gifts', []))}"
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
        game_heading_txt = html.escape(tr["game_heading"].format(game_idx=game_idx))
        html_parts.append(f"<h2><span>{game_heading_txt}</span>{header_place_badge}</h2>")
        html_parts.append(f"<a class='back-to-toc' href='#toc'>{html.escape(tr['back_to_toc'])}</a>")
        html_parts.append("</div>")

        # 試合情報（種族BAN・開始時ヒーロー選択肢）
        if game["active_tribes"] or game["hero_choices"]:
            html_parts.append("<div class='game-info-box'>")

            # 種族（出現 / BAN）
            if game["active_tribes"] or game["banned_tribes"]:
                active_cnt = len(game["active_tribes"])
                is_complete = active_cnt >= 5
                active_label = html.escape(
                    tr["active_tribes_complete"].format(cnt=active_cnt)
                    if is_complete
                    else tr["active_tribes_partial"].format(cnt=active_cnt)
                )
                ban_label = html.escape(
                    tr["banned_tribes_complete"].format(cnt=len(game["banned_tribes"]))
                    if is_complete
                    else tr["banned_tribes_partial"].format(cnt=len(game["banned_tribes"]))
                )
                note_txt = tr["tribe_note_complete"] if is_complete else tr["tribe_note_partial"]
                note_html = f"<span class='game-info-note'>{html.escape(note_txt)}</span>"
                active_chips = "".join(
                    f"<span class='tribe-chip tribe-active'>{html.escape(tribe_labels.get(t, t))}</span>"
                    for t in game["active_tribes"]
                )
                ban_chips = "".join(
                    f"<span class='tribe-chip tribe-ban'>{html.escape(tribe_labels.get(t, t))}</span>"
                    for t in game["banned_tribes"]
                )
                html_parts.append("<div class='game-info-section'>")
                html_parts.append(
                    f"<div class='game-info-title'>{html.escape(tr['tribe_section_title'])} {note_html}</div>"
                )
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
                html_parts.append(
                    f"<div class='game-info-title'>{html.escape(tr['hero_choices_title'])}</div>"
                )
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
                                f"<span class='badge badge-reroll-from'>{html.escape(tr['badge_reroll_from'])}</span>"
                                f"{build_img_tag(prev_cid, is_hero=True)}"
                                f"</div>"
                                f"<span class='hero-reroll-arrow'>→</span>"
                            )
                    badge_html = ""
                    if h_opt["chosen"]:
                        badge_html = f"<span class='badge badge-buy'>{html.escape(tr['badge_chosen'])}</span>"
                    elif h_opt["locked"]:
                        badge_html = f"<span class='badge badge-locked'>{html.escape(tr['badge_locked'])}</span>"
                    html_parts.append(
                        f"<div class='card-item hero-choice-card'>"
                        f"{badge_html}"
                        f"{build_img_tag(h_opt['final_card_id'], is_hero=True)}"
                        f"</div>"
                    )
                    html_parts.append("</div>")
                html_parts.append("</div></div>")

            html_parts.append("</div>")

        prev_hp_keys = None
        for turn in sorted(game["turns"].keys()):
            t_data = game["turns"][turn]
            rolls = t_data["rolls"]
            choice_events_by_roll = group_choice_events_by_roll(t_data)

            start_gold_html = render_coins(
                t_data["gold_start"], t_data["max_gold_start"], label=tr["gold_start_label"]
            )
            tier_html = render_tier_badge(
                t_data["tier_start"], t_data["tier_end"], t_data["upgrade_cost_start"]
            )
            reroll_meta = html.escape(tr["reroll_meta"].format(cnt=max(0, len(rolls) - 1)))

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
                    f"<span class='life-pill' title='{html.escape(tr['life_header_title'])}'>"
                    f"<span class='tier-label'>{html.escape(tr['life_label'])}</span>"
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
                    f"<span class='vs-pill' title='{html.escape(tr['opp_preview_title'])}'>"
                    f"{opp_thumb}<span>VS {opp_name} ({opp_tier_txt})</span>"
                    f"</span>"
                )

            html_parts.append(f"<div id='game-{game_idx}-turn-{turn}' class='turn-box'>")
            html_parts.append(
                f"<div class='turn-title'>"
                f"<span>{html.escape(tr['turn_heading'].format(turn=turn))}</span>"
                f"<span class='turn-meta'>{tier_html}{start_gold_html}{life_header_html}{opp_preview_html}<span>({reroll_meta})</span></span>"
                f"</div>"
            )

            rendered_choice_rolls = set()
            for roll in rolls:
                idx = roll["roll_index"]
                roll_label = html.escape(
                    tr["roll_initial"] if idx == 0 else tr["roll_nth"].format(n=idx)
                )

                roll_gold_html = render_coins(
                    roll["gold_start"], roll["max_gold_start"], label=tr["gold_at_roll"]
                )
                if (
                    roll["gold_end"] != roll["gold_start"]
                    or roll["max_gold_end"] != roll["max_gold_start"]
                ):
                    roll_gold_html += (
                        "<span class='gold-arrow'>→</span>"
                        + render_coins(roll["gold_end"], roll["max_gold_end"], label=tr["gold_after_action"])
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
                html_parts.append(f"<div class='sub-label'>{html.escape(tr['shop_lineup'])}</div>")
                html_parts.append("<div class='card-row'>")

                for cid in roll["carried_over"]:
                    html_parts.append(
                        f"<div class='card-item frozen'>"
                        f"<span class='badge badge-freeze'>{html.escape(tr['badge_frozen'])}</span>"
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
                html_parts.append(f"<div class='sub-label'>{html.escape(tr['bought_in_roll'])}</div>")
                html_parts.append("<div class='card-row'>")
                if roll["bought"]:
                    for cid in roll["bought"]:
                        html_parts.append(
                            f"<div class='card-item bought'>"
                            f"<span class='badge badge-buy'>{html.escape(tr['badge_bought'])}</span>"
                            f"{build_img_tag(cid)}"
                            f"</div>"
                        )
                else:
                    html_parts.append(f"<span class='empty-note'>{html.escape(tr['no_purchases'])}</span>")
                html_parts.append("</div></div>")

                html_parts.append("</div></div>")

                # このロール中に行われた「悪夢の恵み」・発見イベントを時系列順に表示
                if idx in choice_events_by_roll:
                    rendered_choice_rolls.add(idx)
                    for ev_kind, ev_obj in choice_events_by_roll[idx]:
                        if ev_kind == "dg":
                            append_dark_gift_block(ev_obj)
                        else:
                            append_discover_block(ev_obj)

            # ロールに紐づかなかった発見イベントがあればここで表示
            for r_idx, ev_list in sorted(choice_events_by_roll.items()):
                if r_idx not in rendered_choice_rolls:
                    for ev_kind, ev_obj in ev_list:
                        if ev_kind == "dg":
                            append_dark_gift_block(ev_obj)
                        else:
                            append_discover_block(ev_obj)

            # ターン終了時の自分のヒーロー情報・ヒーローパワー・盤面・手札を準備
            end_gold_html = render_coins(
                t_data["gold_end"], t_data["max_gold_end"], label=tr["gold_end_label"]
            )
            hero_powers = t_data.get("hero_powers_end", [])
            cur_hp_keys = tuple(
                (resolve_card_name(hp["card_id"]) if hp.get("card_id") else "")
                or hp.get("name")
                or hp.get("card_id", "")
                for hp in hero_powers
            )
            hp_changed = bool(prev_hp_keys is not None and cur_hp_keys and cur_hp_keys != prev_hp_keys)
            if cur_hp_keys:
                prev_hp_keys = cur_hp_keys
            board = t_data["board_end"]
            hand = t_data["hand_end"]

            def render_hero_power_inline(hp_list, changed=False):
                if not hp_list:
                    return ""
                boxes = []
                for hp in hp_list:
                    hp_cid = hp["card_id"]
                    hp_info = resolve_card_entry(hp_cid)
                    hp_name = (
                        (hp_info["name"] if hp_info and hp_info.get("name") else "")
                        or hp.get("name")
                        or hp_cid
                    )
                    hp_cost = hp.get("cost")
                    if hp_cost is None and hp_info is not None:
                        hp_cost = hp_info.get("cost")
                    hp_text = hp_info.get("text", "") if hp_info else ""
                    box_cls = "hp-inline-box hp-inline-changed" if changed else "hp-inline-box"
                    cost_html = f"<span class='hp-cost-pill'>{hp_cost}G</span>" if hp_cost is not None else ""
                    changed_html = (
                        f"<span class='hp-changed-pill'>{html.escape(tr['hp_changed_badge'])}</span>"
                        if changed
                        else ""
                    )
                    desc_html = (
                        f"<div class='hp-inline-desc'>{html.escape(hp_text)}</div>"
                        if hp_text
                        else ""
                    )
                    thumb_html = build_img_tag(
                        hp_cid,
                        css_class="hp-inline-thumb zoomable-img",
                        alt=hp_name,
                    )
                    boxes.append(
                        f"<div class='{box_cls}'>"
                        f"{thumb_html}"
                        f"<div class='hp-inline-meta'>"
                        f"<div class='hp-inline-top'>"
                        f"<span class='hp-inline-label'>{html.escape(tr['hp_inline_label'])}</span>"
                        f"{cost_html}"
                        f"<span class='hp-inline-name'>{html.escape(hp_name)}</span>"
                        f"{changed_html}"
                        f"</div>"
                        f"{desc_html}"
                        f"</div></div>"
                    )
                return f"<div class='hp-inline-list'>{''.join(boxes)}</div>"

            def render_hero_summary_card(
                hero_entry,
                hp_list,
                is_me=False,
                changed=False,
                extra_top_html="",
                is_ghost=False,
            ):
                if not hero_entry and not hp_list:
                    return ""
                card_cls = "my-summary-card" if is_me else "opp-summary-card"
                thumb_cls = "my-hero-thumb zoomable-img" if is_me else "opp-hero-thumb zoomable-img"
                side_badge = (
                    f"<span class='side-tag side-tag-me'>{html.escape(tr['side_me'])}</span>"
                    if is_me
                    else f"<span class='side-tag side-tag-opp'>{html.escape(tr['side_opp'])}</span>"
                )
                h_name = (
                    html.escape(resolve_hero_name(hero_entry))
                    if hero_entry
                    else html.escape(tr["fallback_me"] if is_me else tr["fallback_opp"])
                )
                h_img = (
                    build_img_tag(
                        hero_entry["card_id"],
                        css_class=thumb_cls,
                        alt=resolve_hero_name(hero_entry),
                        is_hero=True,
                    )
                    if hero_entry and hero_entry.get("card_id")
                    else ""
                )
                meta_chips = []
                if is_ghost:
                    meta_chips.append(f"<span class='opp-meta-chip'>{html.escape(tr['ghost'])}</span>")
                if hero_entry:
                    if hero_entry.get("place"):
                        place_txt = format_place(hero_entry["place"], lang)
                        meta_chips.append(
                            f"<span class='opp-meta-chip'>{html.escape(tr['chip_place'].format(place=place_txt))}</span>"
                        )
                    if "tier_start" in hero_entry and "tier_end" in hero_entry:
                        t_up = hero_entry["tier_end"] > hero_entry["tier_start"]
                        t_cls = "opp-meta-chip opp-tier-up" if t_up else "opp-meta-chip"
                        up_s = " UP" if t_up else ""
                        tier_chip_txt = tr["chip_tier"].format(
                            start=hero_entry["tier_start"],
                            end=hero_entry["tier_end"],
                            up=up_s,
                        )
                        meta_chips.append(f"<span class='{t_cls}'>{html.escape(tier_chip_txt)}</span>")
                    if "hp" in hero_entry and hero_entry["hp"] is not None:
                        life_span = render_life_span(hero_entry["hp"], hero_entry.get("armor", 0))
                        meta_chips.append(
                            f"<span class='opp-meta-chip'>{tr['chip_hp'].format(life=life_span)}</span>"
                        )
                    if "triples" in hero_entry:
                        meta_chips.append(
                            f"<span class='opp-meta-chip'>{html.escape(tr['chip_triples'].format(n=hero_entry['triples']))}</span>"
                        )
                if extra_top_html:
                    meta_chips.append(extra_top_html)

                tr_chips = ""
                if hero_entry:
                    tr_chips = (
                        render_trinket_chip(hero_entry.get("trinket1", 0), tr["trinket_lesser"])
                        + render_trinket_chip(hero_entry.get("trinket2", 0), tr["trinket_greater"])
                    )
                tr_html = f"<div class='trinket-row'>{tr_chips}</div>" if tr_chips else ""
                hp_html = render_hero_power_inline(hp_list, changed=changed)

                return (
                    f"<div class='{card_cls}'>"
                    f"{h_img}"
                    f"<div class='opp-summary-info'>"
                    f"<div class='opp-summary-top'>{side_badge}<span>{h_name}</span>{''.join(meta_chips)}</div>"
                    f"{tr_html}"
                    f"</div>"
                    f"{hp_html}"
                    f"</div>"
                )

            def build_my_board_hand_parts():
                parts = [
                    "<div class='combat-my-boards'>",
                    "<div class='sub-group'>",
                    f"<div class='sub-label'>{html.escape(tr['my_board_label'].format(n=len(board)))}</div>",
                    "<div class='card-row'>",
                ]
                if board:
                    for m in board:
                        parts.append(render_minion_card(m))
                else:
                    parts.append(f"<span class='empty-note'>{html.escape(tr['no_minions'])}</span>")
                parts.append("</div></div>")

                parts.append("<div class='sub-group'>")
                parts.append(f"<div class='sub-label'>{html.escape(tr['my_hand_label'].format(n=len(hand)))}</div>")
                parts.append("<div class='card-row'>")
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
                        parts.append(
                            f"<div class='{' '.join(cls_list)}'>"
                            f"{build_img_tag(h_card['card_id'])}"
                            f"{stat_html}"
                            f"{render_dark_gift_box(h_card['dark_gifts'])}"
                            f"</div>"
                        )
                else:
                    parts.append(f"<span class='empty-note'>{html.escape(tr['no_hand'])}</span>")
                parts.append("</div></div>")
                parts.append("</div>")
                return parts

            # 自分のヒーロー情報（リーダーボードの自分行、無ければターン情報から補完）
            lb_list = t_data.get("leaderboard", [])
            my_lb_entry = next((p for p in lb_list if p["is_me"]), None)
            if my_lb_entry:
                my_hero_entry = my_lb_entry
            else:
                my_hp_rec = t_data.get("my_hp_end_recruit") or t_data.get("my_hp_start")
                my_hero_entry = {
                    "card_id": game.get("hero_card_id", ""),
                    "name": resolve_card_name(game.get("hero_card_id", "")),
                    "tier_start": t_data["tier_start"],
                    "tier_end": t_data["tier_end"],
                    "hp": my_hp_rec[0] if my_hp_rec else None,
                    "armor": my_hp_rec[1] if my_hp_rec else 0,
                }
            my_hero_summary_html = render_hero_summary_card(
                my_hero_entry,
                hero_powers,
                is_me=True,
                changed=hp_changed,
                extra_top_html=end_gold_html,
            )
            my_board_hand_parts = build_my_board_hand_parts()

            # ロビー全員（自分＋敵7人）のリーダーボード一覧（折りたたみ・戦闘前）
            if lb_list:
                html_parts.append("<details class='lb-details'>")
                html_parts.append(
                    f"<summary>{html.escape(tr['lb_summary'].format(n=len(lb_list)))}</summary>"
                )
                html_parts.append("<div class='lb-table-wrap'><table class='lb-table'>")
                html_parts.append(
                    "<thead><tr>"
                    f"<th>{html.escape(tr['lb_col_place'])}</th>"
                    f"<th>{html.escape(tr['lb_col_hero'])}</th>"
                    f"<th>{html.escape(tr['lb_col_tier'])}</th>"
                    f"<th>{html.escape(tr['lb_col_hp'])}</th>"
                    f"<th>{html.escape(tr['lb_col_triples'])}</th>"
                    f"<th>{html.escape(tr['lb_col_trinkets'])}</th>"
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
                        role_tag = f"<span class='lb-tag-me'>{html.escape(tr['lb_tag_me'])}</span>"
                    elif p["is_opponent"]:
                        role_tag = f"<span class='lb-tag-opp'>{html.escape(tr['lb_tag_opp'])}</span>"
                    t_up = p["tier_end"] > p["tier_start"]
                    t_cls = "opp-meta-chip opp-tier-up" if t_up else "opp-meta-chip"
                    up_s = " UP" if t_up else ""
                    tr_html = (
                        render_trinket_chip(p["trinket1"], tr["trinket_lesser"])
                        + render_trinket_chip(p["trinket2"], tr["trinket_greater"])
                    ) or "<span style='color:#6c7586;'>—</span>"
                    place_txt = html.escape(format_place(p["place"], lang))
                    triples_txt = html.escape(tr["lb_triples_val"].format(n=p["triples"]))
                    html_parts.append(
                        f"<tr{tr_attr}>"
                        f"<td><strong>{place_txt}</strong></td>"
                        f"<td><span class='lb-hero-cell'>{p_img}<span>{p_name}</span>{role_tag}</span></td>"
                        f"<td><span class='{t_cls}'>★{p['tier_start']} → ★{p['tier_end']}{up_s}</span></td>"
                        f"<td>{render_life_span(p['hp'], p['armor'])}</td>"
                        f"<td>{triples_txt}</td>"
                        f"<td><div class='trinket-row'>{tr_html}</div></td>"
                        f"</tr>"
                    )
                html_parts.append("</tbody></table></div></details>")

            # 戦闘結果・対戦相手の盤面＆情報（ターン終了時の状況を内包）
            if combat:
                res = combat["result"]
                dmg = combat["damage"]
                if res == "WIN":
                    res_html = f"<span class='combat-res-badge combat-res-win'>{html.escape(tr['combat_win'].format(dmg=dmg))}</span>"
                elif res == "LOSS":
                    res_html = f"<span class='combat-res-badge combat-res-loss'>{html.escape(tr['combat_loss'].format(dmg=dmg))}</span>"
                else:
                    res_html = f"<span class='combat-res-badge combat-res-tie'>{html.escape(tr['combat_tie'])}</span>"

                my_before = combat.get("my_hp_before")
                my_after = combat.get("my_hp_after")
                life_diff_html = ""
                if my_before and my_after:
                    if my_before != my_after:
                        life_diff_html = (
                            f"<span class='life-pill'>"
                            f"<span class='tier-label'>{html.escape(tr['life_label'])}</span>"
                            f"{render_life_span(my_before[0], my_before[1])}"
                            f"<span class='gold-arrow'>→</span>"
                            f"{render_life_span(my_after[0], my_after[1])}"
                            f"</span>"
                        )
                    else:
                        life_diff_html = (
                            f"<span class='life-pill'>"
                            f"<span class='tier-label'>{html.escape(tr['life_label'])}</span>"
                            f"{render_life_span(my_after[0], my_after[1])}"
                            f"</span>"
                        )

                html_parts.append("<div class='combat-block'>")
                html_parts.append(
                    f"<div class='combat-header'>"
                    f"<span>{html.escape(tr['combat_header'])}</span>"
                    f"<span class='roll-gold-bar'>{res_html}{life_diff_html}</span>"
                    f"</div>"
                )

                opp_h = combat.get("opp_hero")
                opp_hp_list = combat.get("opp_hero_powers", [])
                opp_summary_html = render_hero_summary_card(
                    opp_h,
                    opp_hp_list,
                    is_me=False,
                    is_ghost=combat.get("opp_is_ghost", False),
                )
                if opp_summary_html:
                    html_parts.append(opp_summary_html)

                opp_board = combat.get("opp_board", [])
                html_parts.append("<div class='sub-group'>")
                html_parts.append(
                    f"<div class='sub-label'>{html.escape(tr['opp_board_label'].format(n=len(opp_board)))}</div>"
                )
                html_parts.append("<div class='card-row'>")
                if opp_board:
                    for om in opp_board:
                        html_parts.append(render_minion_card(om))
                else:
                    html_parts.append(f"<span class='empty-note'>{html.escape(tr['no_minions'])}</span>")
                html_parts.append("</div></div>")

                html_parts.append("<hr class='combat-divider'>")
                if my_hero_summary_html:
                    html_parts.append(my_hero_summary_html)
                html_parts.extend(my_board_hand_parts)
                html_parts.append("</div>")
            else:
                html_parts.append("<div class='end-turn-block'>")
                html_parts.append(
                    f"<div class='end-turn-header'><span>{html.escape(tr['end_turn_header'])}</span></div>"
                )
                if my_hero_summary_html:
                    html_parts.append(my_hero_summary_html)
                html_parts.extend(my_board_hand_parts)
                html_parts.append("</div>")

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
        f"    <button id='card-modal-close' class='card-modal-close' type='button' aria-label='{html.escape(tr['modal_close_aria'])}'>&times;</button>",
        "    <img id='card-modal-img' class='card-modal-img' src='' alt=''>",
        "    <div id='card-modal-extra' class='card-modal-extra'></div>",
        f"    <div class='card-modal-hint'>{html.escape(tr['modal_hint'])}</div>",
        "  </div>",
        "</div>",
        "<script id='card-catalog' type='application/json'>",
        safe_catalog_json,
        "</script>",
        "</body>",
        "</html>",
    ])

    ensure_parent_dir(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))


def build_catalog_entries(used_card_ids, card_catalog):
    """登場した CardID のカード名・種別・グレード・効果・ヒーローパワー辞書を構築する"""
    by_card_id = card_catalog.get("by_card_id", {})
    by_dbf_id = card_catalog.get("by_dbf_id", {})
    catalog_entries = {}
    for cid in sorted(used_card_ids):
        direct = by_card_id.get(cid)
        info = direct or lookup_card_entry(cid, by_card_id)
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
            hp_dbf_int = safe_int_or_none(hp_dbf)
            hp_info = by_dbf_id.get(hp_dbf_int) if hp_dbf_int is not None else None
            if hp_info:
                hp_obj = {"id": hp_info["id"], "name": hp_info["name"]}
                if hp_info.get("cost") is not None:
                    hp_obj["cost"] = hp_info["cost"]
                if hp_info.get("text"):
                    hp_obj["text"] = hp_info["text"]
                item["hero_power"] = hp_obj
        catalog_entries[cid] = item
    return catalog_entries


def generate_ai_text(games, output_path, card_catalog=None, game_numbers=None, lang="ja"):
    """HTMLと同等の情報をCSS/タグなしで超軽量にまとめたAI分析用Markdownを出力する"""
    lang = normalize_lang(lang)
    tr = I18N[lang]
    tribe_labels = BG_TRIBE_LABELS_BY_LANG[lang]
    discover_source_labels = DISCOVER_SOURCE_LABELS_BY_LANG[lang]
    if card_catalog is None:
        card_catalog = fetch_card_catalog(lang=lang)
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
            return tr["unknown"]
        use_card(cid)
        return lookup_card_name(cid, by_card_id)

    def resolve_hero(entry):
        return lookup_hero_name(entry, by_card_id, tr["unknown"], used_card_ids=used_card_ids)

    def resolve_trinket(dbf_id, slot_label):
        if not dbf_id:
            return ""
        dbf_int = safe_int_or_none(dbf_id)
        info = by_dbf_id.get(dbf_int) if dbf_int is not None else None
        if info:
            use_card(info["id"])
            return f"{slot_label}:{info['name']}"
        return f"{slot_label}:ID{dbf_id}"

    def fmt_life(hp, armor):
        if hp is None:
            return "?"
        if hp <= 0:
            return tr["ai_dead"]
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
        gold_tag = tr["ai_gold_tag"] if m.get("golden") else ""
        name = resolve_name(m["card_id"])
        kws = []
        if m.get("taunt"):
            kws.append(tr["kw_taunt"])
        if m.get("divine_shield"):
            kws.append(tr["kw_ds"])
        if m.get("reborn"):
            kws.append(tr["kw_reborn"])
        if m.get("poisonous"):
            kws.append(tr["kw_poison"])
        if m.get("venomous"):
            kws.append(tr["kw_venom"])
        if m.get("windfury"):
            kws.append(tr["kw_wf"])
        kw_s = f"[{'/'.join(kws)}]" if kws else ""
        dg_s = fmt_dg_names(m.get("dark_gifts", []), with_desc=False)
        dg_part = f"{{{dg_s}}}" if dg_s else ""
        return f"{prefix}{gold_tag}{name}({m['atk']}/{m['health']}){kw_s}{dg_part}"

    def fmt_hand_card(h_card):
        gold_tag = tr["ai_gold_tag"] if h_card.get("golden") else ""
        name = resolve_name(h_card["card_id"])
        stat_s = f"({h_card['atk']}/{h_card['health']})" if h_card.get("card_type") == "MINION" else ""
        dg_s = fmt_dg_names(h_card.get("dark_gifts", []), with_desc=False)
        dg_part = f"{{{dg_s}}}" if dg_s else ""
        return f"{gold_tag}{name}{stat_s}{dg_part}"

    def fmt_trinkets(entry):
        items = [
            resolve_trinket(entry.get("trinket1", 0), tr["trinket_lesser"]),
            resolve_trinket(entry.get("trinket2", 0), tr["trinket_greater"]),
        ]
        items = [x for x in items if x]
        return ", ".join(items)

    lines = [tr["ai_doc_title"], ""]

    for game_idx, game in zip(game_numbers, games):
        sorted_turns = sorted(game["turns"].keys())
        max_tier = max((game["turns"][t]["tier_end"] for t in sorted_turns), default=1)
        hero_name = resolve_name(game["hero_card_id"]) if game.get("hero_card_id") else tr["unknown"]
        place = game.get("final_place")
        if place is not None:
            suffix = "" if game.get("game_completed", False) else tr["place_incomplete_suffix"]
            place_str = tr["ai_place_known"].format(
                place=format_place(place, lang), suffix=suffix
            )
        else:
            place_str = tr["ai_place_unknown"]

        lines.append(
            tr["ai_game_header"].format(
                game_idx=game_idx,
                hero=hero_name,
                place=place_str,
                turns=len(sorted_turns),
                max_tier=max_tier,
            )
        )

        # 種族プール / BAN
        if game["active_tribes"] or game["banned_tribes"]:
            active_cnt = len(game["active_tribes"])
            is_complete = active_cnt >= 5
            active_lbl = (
                tr["ai_active_tribes_complete"].format(cnt=active_cnt)
                if is_complete
                else tr["ai_active_tribes_partial"].format(cnt=active_cnt)
            )
            ban_lbl = (
                tr["ai_banned_tribes_complete"].format(cnt=len(game["banned_tribes"]))
                if is_complete
                else tr["ai_banned_tribes_partial"].format(cnt=len(game["banned_tribes"]))
            )
            active_str = (
                tr["tribe_sep"].join(tribe_labels.get(t, t) for t in game["active_tribes"])
                or tr["none"]
            )
            ban_str = (
                tr["tribe_sep"].join(tribe_labels.get(t, t) for t in game["banned_tribes"])
                or tr["none"]
            )
            lines.append(
                tr["ai_tribes_line"].format(
                    active_lbl=active_lbl,
                    active_str=active_str,
                    ban_lbl=ban_lbl,
                    ban_str=ban_str,
                )
            )

        # 開始時ヒーロー選択肢
        if game["hero_choices"]:
            ordered_heroes = sorted(game["hero_choices"], key=lambda h: (h["locked"], not h["chosen"]))
            choice_parts = []
            for h_opt in ordered_heroes:
                tag = (
                    tr["ai_chosen_tag"]
                    if h_opt["chosen"]
                    else (tr["ai_locked_tag"] if h_opt["locked"] else "")
                )
                final_cid = h_opt["final_card_id"]
                final_s = f"{tag}{resolve_name(final_cid)}({final_cid})"
                hist = h_opt["history"]
                if len(hist) > 1:
                    prev_s = "→".join(f"{resolve_name(pc)}({pc})" for pc in hist[:-1])
                    final_s = f"{final_s}{tr['ai_hero_rerolled_from'].format(prev=prev_s)}"
                choice_parts.append(final_s)
            lines.append(tr["ai_hero_choices_line"].format(choices=" | ".join(choice_parts)))

        lines.append("")

        prev_hp_keys = None
        for turn in sorted_turns:
            t_data = game["turns"][turn]
            rolls = t_data["rolls"]
            reroll_cnt = max(0, len(rolls) - 1)
            up_cost = (
                tr["ai_up_cost"].format(cost=t_data["upgrade_cost_start"])
                if t_data["upgrade_cost_start"] is not None
                else tr["ai_up_cost_max"]
            )
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
                opp_hdr = f"VS {tr['unknown']}"

            lines.append(
                tr["ai_turn_header"].format(
                    turn=turn,
                    t_start=t_data["tier_start"],
                    t_end=t_data["tier_end"],
                    up_mark=tier_up_mark,
                    up_cost=up_cost,
                    gold=start_gold_s,
                    life=life_s,
                    opp=opp_hdr,
                    rerolls=reroll_cnt,
                )
            )

            choice_events_by_roll = group_choice_events_by_roll(t_data)

            def resolve_discover_source_ai(disc_ev):
                return lookup_discover_source(
                    disc_ev,
                    discover_source_labels,
                    by_card_id,
                    tr["discover_default"],
                    used_card_ids=used_card_ids,
                )

            def append_dg_line(dg_ev):
                r_idx = dg_ev["roll_index"]
                timing = (
                    tr["ai_timing_before_reroll"]
                    if r_idx == 0
                    else tr["ai_timing_after_reroll"].format(n=r_idx)
                )
                gold_s = fmt_gold(dg_ev["gold"], dg_ev["max_gold"])
                chosen_set = set(
                    dg_ev.get("chosen_eids")
                    or ([dg_ev["chosen_eid"]] if dg_ev.get("chosen_eid") else [])
                )
                opt_parts = []
                for opt in dg_ev["options"]:
                    chosen_tag = tr["ai_chosen_tag"] if opt["eid"] in chosen_set else ""
                    gold_tag = tr["ai_gold_tag"] if opt.get("golden") else ""
                    c_name = resolve_name(opt["card_id"])
                    dg_desc = fmt_dg_names(opt.get("dark_gifts", []), with_desc=True)
                    dg_part = f"({dg_desc})" if dg_desc else ""
                    opt_parts.append(f"{chosen_tag}{gold_tag}{c_name}{dg_part}")
                lines.append(
                    tr["ai_dg_line"].format(
                        timing=timing, gold=gold_s, opts=" | ".join(opt_parts)
                    )
                )

            def append_discover_line(disc_ev):
                r_idx = disc_ev["roll_index"]
                timing = (
                    tr["ai_timing_before_reroll"]
                    if r_idx == 0
                    else tr["ai_timing_after_reroll"].format(n=r_idx)
                )
                gold_s = fmt_gold(disc_ev["gold"], disc_ev["max_gold"])
                src_label = resolve_discover_source_ai(disc_ev)
                chosen_set = set(
                    disc_ev.get("chosen_eids")
                    or ([disc_ev["chosen_eid"]] if disc_ev.get("chosen_eid") else [])
                )
                opt_parts = []
                for opt in disc_ev["options"]:
                    chosen_tag = tr["ai_chosen_tag"] if opt["eid"] in chosen_set else ""
                    gold_tag = tr["ai_gold_tag"] if opt.get("golden") else ""
                    opt_cid = opt.get("card_id", "")
                    c_name = resolve_name(opt_cid) if opt_cid else (opt.get("name") or tr["unknown"])
                    if opt_cid and c_name == opt_cid and opt.get("name"):
                        c_name = opt["name"]
                    dg_desc = fmt_dg_names(opt.get("dark_gifts", []), with_desc=True)
                    dg_part = f"({dg_desc})" if dg_desc else ""
                    opt_parts.append(f"{chosen_tag}{gold_tag}{c_name}{dg_part}")
                lines.append(
                    tr["ai_discover_line"].format(
                        src=src_label, timing=timing, gold=gold_s, opts=" | ".join(opt_parts)
                    )
                )

            rendered_choice_rolls = set()
            for roll in rolls:
                idx = roll["roll_index"]
                r_lbl = tr["ai_roll_initial"] if idx == 0 else f"R{idx}"
                g_start = fmt_gold(roll["gold_start"], roll["max_gold_start"])
                g_end = fmt_gold(roll["gold_end"], roll["max_gold_end"])
                g_part = f"{g_start}→{g_end}" if g_end != g_start else g_start

                shop_items = [
                    f"{tr['ai_frozen_tag']}{resolve_name(cid)}" for cid in roll["carried_over"]
                ]
                shop_items.extend(resolve_name(cid) for cid in roll["offered"])
                shop_str = ", ".join(shop_items) if shop_items else tr["none"]
                bought_str = (
                    ", ".join(resolve_name(cid) for cid in roll["bought"])
                    if roll["bought"]
                    else tr["none"]
                )
                lines.append(
                    tr["ai_roll_line"].format(
                        r_lbl=r_lbl, gold=g_part, shop=shop_str, bought=bought_str
                    )
                )

                if idx in choice_events_by_roll:
                    rendered_choice_rolls.add(idx)
                    for ev_kind, ev_obj in choice_events_by_roll[idx]:
                        if ev_kind == "dg":
                            append_dg_line(ev_obj)
                        else:
                            append_discover_line(ev_obj)

            for r_idx, ev_list in sorted(choice_events_by_roll.items()):
                if r_idx not in rendered_choice_rolls:
                    for ev_kind, ev_obj in ev_list:
                        if ev_kind == "dg":
                            append_dg_line(ev_obj)
                        else:
                            append_discover_line(ev_obj)

            # ターン終了時の自分のヒーローパワー・盤面・手札文字列を準備
            end_gold_s = fmt_gold(t_data["gold_end"], t_data["max_gold_end"])
            hero_powers = t_data.get("hero_powers_end", [])
            hp_parts = []
            cur_hp_keys = []
            for hp in hero_powers:
                hp_cid = hp["card_id"]
                hp_name = resolve_name(hp_cid) if hp_cid else (hp.get("name") or tr["unknown"])
                if hp_cid and hp_name == hp_cid and hp.get("name"):
                    hp_name = hp["name"]
                cur_hp_keys.append(hp_name or hp_cid)
                hp_info = lookup_card_entry(hp_cid, by_card_id)
                hp_cost = hp.get("cost")
                if hp_cost is None and hp_info is not None:
                    hp_cost = hp_info.get("cost")
                cost_s = f"({hp_cost}G)" if hp_cost is not None else ""
                hp_parts.append(f"{hp_name}{cost_s}")
            cur_hp_tuple = tuple(cur_hp_keys)
            hp_changed = bool(prev_hp_keys is not None and cur_hp_tuple and cur_hp_tuple != prev_hp_keys)
            if cur_hp_tuple:
                prev_hp_keys = cur_hp_tuple
            hp_str = " / ".join(hp_parts)
            if hp_str and hp_changed:
                hp_str += f" {tr['ai_changed_tag']}"
            board = t_data["board_end"]
            hand = t_data["hand_end"]
            board_str = (
                " / ".join(fmt_minion(m, i) for i, m in enumerate(board, start=1))
                if board
                else tr["none"]
            )
            hand_str = ", ".join(fmt_hand_card(h) for h in hand) if hand else tr["none"]

            # ロビー全員の状況（戦闘前・1行に圧縮）
            lb_list = t_data.get("leaderboard", [])
            if lb_list:
                lb_parts = []
                for p in lb_list:
                    role = (
                        tr["ai_role_me"]
                        if p["is_me"]
                        else (tr["ai_role_opp"] if p["is_opponent"] else "")
                    )
                    t_s = f"★{p['tier_start']}→{p['tier_end']}" if p["tier_end"] != p["tier_start"] else f"★{p['tier_end']}"
                    tr_s = fmt_trinkets(p)
                    tr_part = f",{tr_s}" if tr_s else ""
                    lb_parts.append(
                        f"{format_place(p['place'], lang)}:{role}{resolve_hero(p)}({t_s},{fmt_life(p['hp'], p['armor'])},T{p['triples']}{tr_part})"
                    )
                lines.append(tr["ai_lobby_line"].format(items=" / ".join(lb_parts)))

            # 戦闘結果・相手盤面（ターン終了時の自分の盤面・手札を内包）
            if combat:
                res = combat["result"]
                dmg = combat["damage"]
                res_s = (
                    tr["ai_combat_win"].format(dmg=dmg)
                    if res == "WIN"
                    else (tr["ai_combat_loss"].format(dmg=dmg) if res == "LOSS" else tr["ai_combat_tie"])
                )
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
                        opp_parts.append(format_place(opp_h["place"], lang))
                    if "tier_start" in opp_h and "tier_end" in opp_h:
                        opp_parts.append(f"★{opp_h['tier_start']}→★{opp_h['tier_end']}")
                    if "hp" in opp_h:
                        opp_parts.append(f"HP{fmt_life(opp_h['hp'], opp_h.get('armor', 0))}")
                    if "triples" in opp_h:
                        opp_parts.append(tr["ai_opp_triples"].format(n=opp_h["triples"]))
                    tr_s = fmt_trinkets(opp_h)
                    if tr_s:
                        opp_parts.append(tr_s)
                    opp_hp_parts = []
                    for ohp in combat.get("opp_hero_powers", []):
                        ohp_cid = ohp["card_id"]
                        ohp_name = resolve_name(ohp_cid) if ohp_cid else (ohp.get("name") or tr["unknown"])
                        if ohp_cid and ohp_name == ohp_cid and ohp.get("name"):
                            ohp_name = ohp["name"]
                        ohp_info = lookup_card_entry(ohp_cid, by_card_id)
                        ohp_cost = ohp.get("cost")
                        if ohp_cost is None and ohp_info is not None:
                            ohp_cost = ohp_info.get("cost")
                        ocost_s = f"({ohp_cost}G)" if ohp_cost is not None else ""
                        opp_hp_parts.append(f"{ohp_name}{ocost_s}")
                    if opp_hp_parts:
                        opp_parts.append(f"{tr['ai_opp_hp_prefix']}{' / '.join(opp_hp_parts)}")
                    elif combat.get("opp_is_ghost"):
                        opp_parts.append(tr["ghost"])
                    opp_info = tr["ai_opp_info"].format(parts=" / ".join(opp_parts))

                lines.append(
                    tr["ai_combat_line"].format(res=res_s, life=life_diff, opp_info=opp_info)
                )
                opp_board = combat.get("opp_board", [])
                opp_board_str = (
                    " / ".join(fmt_minion(om, i) for i, om in enumerate(opp_board, start=1))
                    if opp_board
                    else tr["none"]
                )
                lines.append(
                    tr["ai_opp_board_line"].format(n=len(opp_board), board=opp_board_str)
                )
                if hp_str:
                    lines.append(tr["ai_my_hp_line"].format(hp=hp_str))
                lines.append(
                    tr["ai_my_board_line"].format(
                        tier=t_data["tier_end"],
                        gold=end_gold_s,
                        n=len(board),
                        board=board_str,
                    )
                )
                if hand:
                    lines.append(tr["ai_hand_line"].format(n=len(hand), hand=hand_str))
            else:
                lines.append(
                    tr["ai_end_turn_board_line"].format(
                        tier=t_data["tier_end"],
                        gold=end_gold_s,
                        n=len(board),
                        board=board_str,
                    )
                )
                if hp_str:
                    lines.append(tr["ai_my_hp_line"].format(hp=hp_str))
                if hand:
                    lines.append(tr["ai_hand_line"].format(n=len(hand), hand=hand_str))

            lines.append("")

    # 登場カード辞書（カテゴリ別に整形）
    catalog_entries = build_catalog_entries(used_card_ids, card_catalog)
    heroes_cat = []
    hero_powers_cat = []
    minions_cat = []
    spells_cat = []
    trinkets_cat = []
    others_cat = []

    for cid, item in catalog_entries.items():
        ctype = item.get("type", "")
        if ctype == "HERO":
            heroes_cat.append((cid, item))
        elif ctype == "HERO_POWER":
            hero_powers_cat.append((cid, item))
        elif ctype == "MINION":
            minions_cat.append((cid, item))
        elif ctype == "BATTLEGROUND_SPELL":
            spells_cat.append((cid, item))
        elif ctype == "BATTLEGROUND_TRINKET":
            trinkets_cat.append((cid, item))
        else:
            others_cat.append((cid, item))

    lines.append(tr["ai_catalog_title"])
    lines.append("")

    if heroes_cat:
        lines.append(tr["ai_cat_heroes"])
        for cid, item in sorted(heroes_cat, key=lambda x: x[1]["name"]):
            hp = item.get("hero_power")
            if hp:
                hp_cost = f"({hp['cost']}G) " if hp.get("cost") is not None else ""
                hp_text = hp.get("text", "")
                lines.append(
                    tr["ai_cat_hero_with_hp"]
                    .format(
                        name=item["name"],
                        cid=cid,
                        hp_name=hp["name"],
                        hp_cost=hp_cost,
                        hp_text=hp_text,
                    )
                    .rstrip()
                )
            else:
                lines.append(f"- {item['name']} ({cid})")
        lines.append("")

    if minions_cat:
        lines.append(tr["ai_cat_minions"])
        for cid, item in sorted(minions_cat, key=lambda x: (x[1].get("tier") or 99, x[1]["name"], cid)):
            tier_s = f"★{item['tier']} " if item.get("tier") is not None else ""
            gold_s = tr["ai_gold_tag"] if cid.endswith("_G") or item.get("golden") else ""
            tribes_s = f"[{'/'.join(item['tribes'])}] " if item.get("tribes") else ""
            stat_s = f"{item['atk']}/{item['hp']} " if "atk" in item and "hp" in item else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {tier_s}{gold_s}{item['name']} {tribes_s}{stat_s}({cid}){text_s}")
        lines.append("")

    if spells_cat:
        lines.append(tr["ai_cat_spells"])
        for cid, item in sorted(spells_cat, key=lambda x: (x[1].get("tier") or 99, x[1]["name"], cid)):
            tier_s = f"★{item['tier']} " if item.get("tier") is not None else ""
            cost_s = f"{item['cost']}G, " if item.get("cost") is not None else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {tier_s}{item['name']} ({cost_s}{cid}){text_s}")
        lines.append("")

    if trinkets_cat:
        lines.append(tr["ai_cat_trinkets"])
        for cid, item in sorted(trinkets_cat, key=lambda x: (x[1]["name"], cid)):
            cost_s = f"{item['cost']}G, " if item.get("cost") is not None else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {item['name']} ({cost_s}{cid}){text_s}")
        lines.append("")

    if hero_powers_cat:
        lines.append(tr["ai_cat_hero_powers"])
        for cid, item in sorted(hero_powers_cat, key=lambda x: (x[1]["name"], cid)):
            cost_s = f"{item['cost']}G, " if item.get("cost") is not None else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {item['name']} ({cost_s}{cid}){text_s}")
        lines.append("")

    if others_cat:
        lines.append(tr["ai_cat_others"])
        for cid, item in sorted(others_cat, key=lambda x: (x[1]["name"], cid)):
            cost_s = f"{item['cost']}G, " if item.get("cost") is not None else ""
            text_s = f": {item['text']}" if item.get("text") else ""
            lines.append(f"- {item['name']} ({cost_s}{cid}){text_s}")
        lines.append("")

    if used_dg_ids:
        lines.append(tr["ai_cat_dark_gifts"])
        seen_dg = set()
        for dg_cid in sorted(used_dg_ids):
            name, desc = dark_gift_db.get(dg_cid, (dg_cid, ""))
            if (name, desc) in seen_dg:
                continue
            seen_dg.add((name, desc))
            lines.append(f"- ✦ {name}: {desc}" if desc else f"- ✦ {name}")
        lines.append("")

    ensure_parent_dir(output_path)
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


def main(argv=None):
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
    parser.add_argument(
        "-l",
        "--lang",
        choices=SUPPORTED_LANGS,
        default="ja",
        help="出力レポート（HTML・AI用Markdown）の言語を指定（デフォルト: ja）",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="ローカルキャッシュを無視して HearthstoneJSON から最新カードマスタを再取得する",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="ネットワークアクセスを行わず、ローカルキャッシュ（未取得時は CardID）のみ使用する",
    )
    args = parser.parse_args(argv)

    emit_ai = args.ai_text or args.ai_only
    emit_html = not args.ai_only

    if args.log_file is not None:
        if not os.path.exists(args.log_file):
            print(f"指定されたログファイルが見つかりませんでした: {args.log_file}")
            sys.exit(1)
        log_file = args.log_file
    else:
        log_file = find_latest_power_log()
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

    card_catalog = fetch_card_catalog(
        lang=args.lang,
        refresh_cache=args.refresh_cache,
        offline=args.offline,
    )

    if args.split:
        for game_idx, game in target_pairs:
            place = game.get("final_place")
            place_str = f"{format_place(place, args.lang)}・" if place is not None else ""
            turns_n = len(game["turns"])
            if emit_html:
                out_path = build_split_output_path(args.output, game_idx)
                generate_html(
                    [game],
                    out_path,
                    card_catalog=card_catalog,
                    game_numbers=[game_idx],
                    lang=args.lang,
                )
                size_kb = os.path.getsize(out_path) / 1024
                print(f"HTML出力完了: {os.path.abspath(out_path)} （第 {game_idx} 試合 / {place_str}{turns_n}T / {size_kb:.1f} KB）")
            if emit_ai:
                ai_path = build_ai_output_path(args.output, game_idx=game_idx, ai_only=args.ai_only)
                generate_ai_text(
                    [game],
                    ai_path,
                    card_catalog=card_catalog,
                    game_numbers=[game_idx],
                    lang=args.lang,
                )
                size_kb = os.path.getsize(ai_path) / 1024
                print(f"AIテキスト出力完了: {os.path.abspath(ai_path)} （第 {game_idx} 試合 / {place_str}{turns_n}T / {size_kb:.1f} KB）")
    else:
        game_nums = [idx for idx, _ in target_pairs]
        games_to_write = [g for _, g in target_pairs]
        if emit_html:
            generate_html(
                games_to_write,
                args.output,
                card_catalog=card_catalog,
                game_numbers=game_nums,
                lang=args.lang,
            )
            size_kb = os.path.getsize(args.output) / 1024
            print(f"HTML出力完了: {os.path.abspath(args.output)} （{len(games_to_write)} / 全 {len(parsed_games)} 試合 / {size_kb:.1f} KB）")
        if emit_ai:
            ai_path = build_ai_output_path(args.output, game_idx=None, ai_only=args.ai_only)
            generate_ai_text(
                games_to_write,
                ai_path,
                card_catalog=card_catalog,
                game_numbers=game_nums,
                lang=args.lang,
            )
            size_kb = os.path.getsize(ai_path) / 1024
            print(f"AIテキスト出力完了: {os.path.abspath(ai_path)} （{len(games_to_write)} / 全 {len(parsed_games)} 試合 / {size_kb:.1f} KB）")


if __name__ == "__main__":
    main()
