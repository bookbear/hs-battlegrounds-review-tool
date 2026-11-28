import gzip
import html
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

import bg_review


SAMPLE_RAW_CARDS_EN = [
    {
        "id": "TB_BaconShop_HERO_43",
        "dbfId": 60367,
        "name": "Dinotamer Brann",
        "type": "HERO",
        "heroPowerDbfId": 60368,
    },
    {
        "id": "TB_BaconShop_HERO_43_Buddy_HP",
        "dbfId": 60368,
        "name": "Battle Brand",
        "type": "HERO_POWER",
        "cost": 0,
        "text": "[x]<b>Passive</b>\nAfter you buy 5 <b>Battlecry</b> minions, get a Brann Bronzebeard.",
    },
    {
        "id": "TB_BaconShop_HERO_40",
        "dbfId": 60360,
        "name": "Sir Finley Mrrgglton",
        "type": "HERO",
    },
    {
        "id": "BG28_HERO_801",
        "dbfId": 100001,
        "name": "Doctor Holli'dae",
        "type": "HERO",
        "heroPowerDbfId": 100002,
    },
    {
        "id": "BG28_HERO_801p",
        "dbfId": 100002,
        "name": "Blessing of the Nine Frogs",
        "type": "HERO_POWER",
        "cost": 1,
        "text": "Get a random Tavern spell.",
    },
    {
        "id": "BG_Minion_01",
        "dbfId": 200001,
        "name": "Razorfen Geomancer",
        "type": "MINION",
        "techLevel": 1,
        "attack": 3,
        "health": 1,
        "races": ["QUILBOAR"],
        "text": "<b>Battlecry:</b> Get a <b>Blood Gem</b>.",
    },
    {
        "id": "BG_Minion_02",
        "dbfId": 200002,
        "name": "Rodeo Performer",
        "type": "MINION",
        "techLevel": 5,
        "attack": 3,
        "health": 4,
        "text": "<b>Battlecry:</b> <b>Discover</b> a Tavern spell.",
    },
    {
        "id": "BG_Minion_03",
        "dbfId": 200003,
        "name": "Scarlet Skull",
        "type": "MINION",
        "techLevel": 2,
        "attack": 2,
        "health": 1,
        "races": ["UNDEAD"],
        "text": "<b>Reborn</b>",
    },
    {
        "id": "BG_Spell_01",
        "dbfId": 200010,
        "name": "Tavern Coin",
        "type": "BATTLEGROUND_SPELL",
        "techLevel": 1,
        "cost": 1,
        "text": "Gain 1 Gold.",
    },
    {
        "id": "BG30_MagicItem_001",
        "dbfId": 300001,
        "name": "Dragon Skull",
        "type": "BATTLEGROUND_TRINKET",
        "cost": 2,
        "text": "At the start of each turn, get a Dragon.",
    },
    {
        "id": "BG36_MidGameEffect_000t1",
        "dbfId": 400001,
        "name": "Harpy's Talons",
        "type": "SPELL",
        "text": "<b>Divine Shield</b>, <b>Windfury</b>",
    },
]

SAMPLE_RAW_CARDS_JA = [
    {
        "id": "TB_BaconShop_HERO_43",
        "dbfId": 60367,
        "name": "恐竜使いブラン",
        "type": "HERO",
        "heroPowerDbfId": 60368,
    },
    {
        "id": "TB_BaconShop_HERO_43_Buddy_HP",
        "dbfId": 60368,
        "name": "バトルブランド",
        "type": "HERO_POWER",
        "cost": 0,
        "text": "[x]<b>常時発動</b>\n雄叫びミニオンを5体買った後、ブラン・ブロンズビアードを1体得る。",
    },
    {
        "id": "TB_BaconShop_HERO_40",
        "dbfId": 60360,
        "name": "サー・フィンレー・マルグルトン",
        "type": "HERO",
    },
    {
        "id": "BG28_HERO_801",
        "dbfId": 100001,
        "name": "ドクター・ホリ＝デイ",
        "type": "HERO",
        "heroPowerDbfId": 100002,
    },
    {
        "id": "BG28_HERO_801p",
        "dbfId": 100002,
        "name": "九蛙の祝福",
        "type": "HERO_POWER",
        "cost": 1,
        "text": "ランダムな酒場の呪文を1枚得る。",
    },
    {
        "id": "BG_Minion_01",
        "dbfId": 200001,
        "name": "レイザーフェン・ジオマンサー",
        "type": "MINION",
        "techLevel": 1,
        "attack": 3,
        "health": 1,
        "races": ["QUILBOAR"],
        "text": "<b>雄叫び:</b> <b>血の宝石</b>を1個得る。",
    },
    {
        "id": "BG_Minion_02",
        "dbfId": 200002,
        "name": "ロデオ・パフォーマー",
        "type": "MINION",
        "techLevel": 5,
        "attack": 3,
        "health": 4,
        "text": "<b>雄叫び:</b> 酒場の呪文を1枚<b>発見</b>する。",
    },
    {
        "id": "BG_Minion_03",
        "dbfId": 200003,
        "name": "スカーレット・スカル",
        "type": "MINION",
        "techLevel": 2,
        "attack": 2,
        "health": 1,
        "races": ["UNDEAD"],
        "text": "<b>蘇り</b>",
    },
    {
        "id": "BG_Spell_01",
        "dbfId": 200010,
        "name": "酒場のコイン",
        "type": "BATTLEGROUND_SPELL",
        "techLevel": 1,
        "cost": 1,
        "text": "1ゴールドを獲得する。",
    },
    {
        "id": "BG30_MagicItem_001",
        "dbfId": 300001,
        "name": "ドラゴンの頭蓋骨",
        "type": "BATTLEGROUND_TRINKET",
        "cost": 2,
        "text": "各ターンの開始時、ドラゴンを1体得る。",
    },
    {
        "id": "BG36_MidGameEffect_000t1",
        "dbfId": 400001,
        "name": "ハーピーの爪",
        "type": "SPELL",
        "text": "<b>聖なる盾</b>、<b>疾風</b>",
    },
]


def build_synthetic_power_log():
    """非BG試合 + BG試合（スペース入りプレイヤー名・リロール・凍結・発見・恵み・戦闘・途中終了）を含む合成ログ"""
    lines = [
        # --- 1. 非バトルグラウンド試合（除外されるべき） ---
        "D 10:00:00.000 GameState.DebugPrintPower() - CREATE_GAME",
        "D 10:00:00.001 GameState.DebugPrintGame() - GameType=GT_RANKED",
        "D 10:00:00.002 GameState.DebugPrintPower() - Player EntityID=2 PlayerID=1 GameAccountId=[hi=1 lo=123]",
        "D 10:00:00.003 GameState.DebugPrintGame() - PlayerID=1, PlayerName=Test Player#1234",
        "D 10:00:00.004 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=CURRENT_PLAYER value=1",
        "D 10:00:00.005 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=TURN value=1",
        # --- 2. バトルグラウンド試合 ---
        "D 10:05:00.000 GameState.DebugPrintPower() - CREATE_GAME",
        "D 10:05:00.001 GameState.DebugPrintGame() - GameType=GT_BATTLEGROUNDS",
        "D 10:05:00.002 GameState.DebugPrintPower() - Player EntityID=2 PlayerID=1 GameAccountId=[hi=144 lo=99999]",
        "D 10:05:00.003 GameState.DebugPrintPower() -     tag=NEXT_OPPONENT_PLAYER_ID value=2",
        "D 10:05:00.004 GameState.DebugPrintPower() - Player EntityID=3 PlayerID=15 GameAccountId=[hi=0 lo=0]",
        "D 10:05:00.005 GameState.DebugPrintGame() - PlayerID=1, PlayerName=Test Player#1234",
        # 開始時ヒーロー選択肢（1枠はリロール前→変更後、1枠はロック）
        "D 10:05:00.010 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=10 CardID=TB_BaconShop_HERO_40",
        "D 10:05:00.011 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO",
        "D 10:05:00.012 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=11 CardID=BG28_HERO_801",
        "D 10:05:00.013 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO",
        "D 10:05:00.014 GameState.DebugPrintPower() -     tag=BACON_LOCKED_MULLIGAN_HERO value=1",
        "D 10:05:00.015 GameState.DebugPrintPower() - CHANGE_ENTITY - Updating Entity=[entityName=恐竜使いブラン id=10 zone=HAND] CardID=TB_BaconShop_HERO_43",
        "D 10:05:00.020 GameState.DebugPrintEntityChoices() - id=1 Player=Test Player#1234 TaskList=1 ChoiceType=MULLIGAN CountMin=1 CountMax=1",
        "D 10:05:00.021 GameState.DebugPrintEntityChoices() -   Entities[0]=[entityName=恐竜使いブラン id=10 cardId=TB_BaconShop_HERO_43]",
        "D 10:05:00.022 GameState.DebugPrintEntityChoices() -   Entities[1]=[entityName=ドクター・ホリ＝デイ id=11 cardId=BG28_HERO_801]",
        "D 10:05:00.025 GameState.DebugPrintEntitiesChosen() - id=1 Player=Test Player#1234 EntitiesCount=1",
        "D 10:05:00.026 GameState.DebugPrintEntitiesChosen() -   Entities[0]=[entityName=恐竜使いブラン id=10 cardId=TB_BaconShop_HERO_43]",
        # 自分のヒーロー & ヒロパ & アップグレードボタン
        "D 10:05:01.000 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=HERO_ENTITY value=10",
        "D 10:05:01.001 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=恐竜使いブラン id=10 zone=PLAY] tag=HEALTH value=30 DEF CHANGE",
        "D 10:05:01.002 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=恐竜使いブラン id=10 zone=PLAY] tag=ARMOR value=10",
        "D 10:05:01.003 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=恐竜使いブラン id=10 zone=PLAY] tag=PLAYER_LEADERBOARD_PLACE value=1",
        "D 10:05:01.004 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=恐竜使いブラン id=10 zone=PLAY] tag=BACON_FIRST_TRINKET_DATABASE_ID value=300001",
        "D 10:05:01.005 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=12 CardID=TB_BaconShop_HERO_43_Buddy_HP",
        "D 10:05:01.006 GameState.DebugPrintPower() -     tag=CONTROLLER value=1",
        "D 10:05:01.007 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:01.008 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO_POWER",
        "D 10:05:01.009 GameState.DebugPrintPower() -     tag=COST value=0",
        "D 10:05:01.010 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=13 CardID=TB_BaconShopTechUp02_Button",
        "D 10:05:01.011 GameState.DebugPrintPower() -     tag=CONTROLLER value=1",
        "D 10:05:01.012 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:01.013 GameState.DebugPrintPower() -     tag=COST value=5",
        # リーダーボード上の対戦相手（日本語ログ由来の entityName を持つ）
        "D 10:05:01.020 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=20 CardID=BG28_HERO_801",
        "D 10:05:01.021 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:01.022 GameState.DebugPrintPower() -     tag=ZONE value=SETASIDE",
        "D 10:05:01.023 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO",
        "D 10:05:01.024 GameState.DebugPrintPower() -     tag=PLAYER_ID value=2",
        "D 10:05:01.025 GameState.DebugPrintPower() -     tag=PLAYER_LEADERBOARD_PLACE value=2",
        "D 10:05:01.026 GameState.DebugPrintPower() -     tag=PLAYER_TECH_LEVEL value=1",
        "D 10:05:01.027 GameState.DebugPrintPower() -     tag=HEALTH value=30",
        "D 10:05:01.028 GameState.DebugPrintPower() -     tag=ARMOR value=12",
        "D 10:05:01.029 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=ドクター・ホリ＝デイ id=20 zone=SETASIDE] tag=PLAYER_TRIPLES value=1",
        # --- ターン1 雇用フェーズ ---
        "D 10:05:02.000 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=CURRENT_PLAYER value=1",
        "D 10:05:02.001 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=TURN value=1",
        "D 10:05:02.002 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=RESOURCES value=3",
        "D 10:05:02.003 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=RESOURCES_USED value=0",
        # 初期酒場（キルボア1体 + アンデッド1体）
        "D 10:05:02.010 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=101 CardID=BG_Minion_01",
        "D 10:05:02.011 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:02.012 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:02.013 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
        "D 10:05:02.014 GameState.DebugPrintPower() -     tag=ATK value=3",
        "D 10:05:02.015 GameState.DebugPrintPower() -     tag=HEALTH value=1",
        "D 10:05:02.016 GameState.DebugPrintPower() -     tag=IS_BACON_POOL_MINION value=1",
        "D 10:05:02.017 GameState.DebugPrintPower() -     tag=BACON_SUBSET_QUILLBOAR value=1",
        "D 10:05:02.020 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=102 CardID=BG_Minion_03",
        "D 10:05:02.021 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:02.022 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:02.023 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
        "D 10:05:02.024 GameState.DebugPrintPower() -     tag=ATK value=2",
        "D 10:05:02.025 GameState.DebugPrintPower() -     tag=HEALTH value=1",
        "D 10:05:02.026 GameState.DebugPrintPower() -     tag=IS_BACON_POOL_MINION value=1",
        "D 10:05:02.027 GameState.DebugPrintPower() -     tag=BACON_SUBSET_UNDEAD value=1",
        "D 10:05:02.030 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION",
        # 異常値タグ（クラッシュしないことを確認）
        "D 10:05:02.035 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=レイザーフェン・ジオマンサー id=101] tag=ATK value=NOT_A_NUMBER",
        # 購入して盤面に出す + 恵みエンチャントを付与
        "D 10:05:02.040 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=RESOURCES_USED value=3",
        "D 10:05:02.041 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=レイザーフェン・ジオマンサー id=101] tag=CONTROLLER value=1",
        "D 10:05:02.042 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=レイザーフェン・ジオマンサー id=101] tag=ZONE value=HAND",
        "D 10:05:02.043 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=レイザーフェン・ジオマンサー id=101] tag=ZONE value=PLAY",
        "D 10:05:02.044 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=レイザーフェン・ジオマンサー id=101] tag=ZONE_POSITION value=1",
        "D 10:05:02.045 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=レイザーフェン・ジオマンサー id=101] tag=DIVINE_SHIELD value=1",
        "D 10:05:02.046 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=150 CardID=EDR_100t1e",
        "D 10:05:02.047 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:02.048 GameState.DebugPrintPower() -     tag=ATTACHED value=101",
        # ゴールデンミニオン由来の発見（_G サフィックスの名前解決テスト）
        "D 10:05:02.050 GameState.DebugPrintEntityChoices() - id=2 Player=Test Player#1234 TaskList=2 ChoiceType=GENERAL CountMin=1 CountMax=1",
        "D 10:05:02.051 GameState.DebugPrintEntityChoices() -   Source=[entityName=ロデオ・パフォーマー id=200 cardId=BG_Minion_02_G]",
        "D 10:05:02.052 GameState.DebugPrintEntityChoices() -   Entities[0]=[entityName=酒場のコイン id=201 cardId=BG_Spell_01]",
        "D 10:05:02.053 GameState.DebugPrintEntitiesChosen() - id=2 Player=Test Player#1234 EntitiesCount=1",
        "D 10:05:02.054 GameState.DebugPrintEntitiesChosen() -   Entities[0]=[entityName=酒場のコイン id=201 cardId=BG_Spell_01]",
        # 残った酒場ミニオン(102)を凍結して次ターンへ持ち越す
        "D 10:05:02.060 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=スカーレット・スカル id=102] tag=FROZEN value=1",
        # --- ターン1 戦闘フェーズ ---
        "D 10:05:10.000 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=CURRENT_PLAYER value=0",
        "D 10:05:10.005 GameState.DebugPrintPower() - TAG_CHANGE Entity=[id=102] tag=ZONE value=SETASIDE",
        "D 10:05:10.010 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=300 CardID=BG28_HERO_801",
        "D 10:05:10.011 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:10.012 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:10.013 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO",
        "D 10:05:10.014 GameState.DebugPrintPower() -     tag=HEALTH value=30",
        "D 10:05:10.015 GameState.DebugPrintPower() -     tag=ARMOR value=12",
        "D 10:05:10.016 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=301 CardID=BG28_HERO_801p",
        "D 10:05:10.017 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:10.018 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:10.019 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO_POWER",
        "D 10:05:10.020 GameState.DebugPrintPower() -     tag=COST value=1",
        "D 10:05:10.021 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=302 CardID=BG_Minion_03",
        "D 10:05:10.022 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:10.023 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:10.024 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
        "D 10:05:10.025 GameState.DebugPrintPower() -     tag=ATK value=2",
        "D 10:05:10.026 GameState.DebugPrintPower() -     tag=HEALTH value=1",
        "D 10:05:10.027 GameState.DebugPrintPower() -     tag=REBORN value=1",
        "D 10:05:10.030 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION",
        "D 10:05:10.040 GameState.DebugPrintPower() - BLOCK_START BlockType=ATTACK Entity=[entityName=恐竜使いブラン id=10 zone=PLAY]",
        "D 10:05:10.041 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=ドクター・ホリ＝デイ id=300] tag=PREDAMAGE value=4",
        "D 10:05:10.050 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_END",
        # --- ターン2 雇用フェーズ（凍結持ち越し + リロール + 戦闘中EOF） ---
        "D 10:05:20.000 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=CURRENT_PLAYER value=1",
        "D 10:05:20.001 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=TURN value=2",
        "D 10:05:20.002 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=RESOURCES value=4",
        "D 10:05:20.003 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=RESOURCES_USED value=0",
        "D 10:05:20.010 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=401 CardID=BG_Minion_03",
        "D 10:05:20.011 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:20.012 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:20.013 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
        "D 10:05:20.014 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=402 CardID=BG_Spell_01",
        "D 10:05:20.015 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:20.016 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:20.017 GameState.DebugPrintPower() -     tag=CARDTYPE value=BATTLEGROUND_SPELL",
        "D 10:05:20.020 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION",
        # リロール実行
        "D 10:05:20.030 GameState.DebugPrintPower() - BLOCK_START BlockType=PLAY Entity=[entityName=リロール id=50 cardId=TB_BaconShop_8p_Reroll_Button]",
        "D 10:05:20.031 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=RESOURCES_USED value=1",
        "D 10:05:20.032 GameState.DebugPrintPower() - TAG_CHANGE Entity=[id=401] tag=ZONE value=REMOVEDFROMGAME",
        "D 10:05:20.033 GameState.DebugPrintPower() - TAG_CHANGE Entity=[id=402] tag=ZONE value=REMOVEDFROMGAME",
        "D 10:05:20.034 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=403 CardID=BG_Minion_02",
        "D 10:05:20.035 GameState.DebugPrintPower() -     tag=CONTROLLER value=15",
        "D 10:05:20.036 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
        "D 10:05:20.037 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
        # 戦闘開始後に MAIN_END 無しで EOF（戦闘結果が確定されることを確認）
        "D 10:05:30.000 GameState.DebugPrintPower() - TAG_CHANGE Entity=Test Player#1234 tag=CURRENT_PLAYER value=0",
        "D 10:05:30.010 GameState.DebugPrintPower() - BLOCK_START BlockType=ATTACK Entity=[entityName=ドクター・ホリ＝デイ id=300 zone=PLAY]",
        "D 10:05:30.011 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=恐竜使いブラン id=10] tag=PREDAMAGE value=5",
    ]
    return "\n".join(lines) + "\n"


class TestHelpers(unittest.TestCase):
    def test_normalize_lang_and_locale(self):
        self.assertEqual(bg_review.normalize_lang("EN"), "en")
        self.assertEqual(bg_review.normalize_lang("ja"), "ja")
        self.assertEqual(bg_review.normalize_lang("fr"), "ja")
        self.assertEqual(bg_review.get_hs_locale("en"), "enUS")
        self.assertEqual(bg_review.get_hs_locale("ja"), "jaJP")

    def test_format_place(self):
        self.assertEqual(bg_review.format_place(1, "ja"), "1位")
        self.assertEqual(bg_review.format_place(1, "en"), "1st")
        self.assertEqual(bg_review.format_place(2, "en"), "2nd")
        self.assertEqual(bg_review.format_place(3, "en"), "3rd")
        self.assertEqual(bg_review.format_place(4, "en"), "4th")
        self.assertEqual(bg_review.format_place(11, "en"), "11th")
        self.assertEqual(bg_review.format_place(12, "en"), "12th")
        self.assertEqual(bg_review.format_place(13, "en"), "13th")
        self.assertEqual(bg_review.format_place(21, "en"), "21st")

    def test_normalize_dark_gift_id(self):
        self.assertEqual(bg_review.normalize_dark_gift_id("EDR_100t1e"), "BG36_MidGameEffect_000t1")
        self.assertEqual(bg_review.normalize_dark_gift_id("BG36_MidGameEffect_000t4e2"), "BG36_MidGameEffect_000t4")
        self.assertEqual(bg_review.normalize_dark_gift_id("BG_Minion_01"), "")

    def test_clean_card_text(self):
        self.assertEqual(
            bg_review.clean_card_text("[x]<b>雄叫び:</b>\nテスト（0回）", lang="ja"),
            "雄叫び:テスト",
        )
        self.assertEqual(
            bg_review.clean_card_text("[x]<b>Battlecry:</b>\nTest\xa0(0)", lang="en"),
            "Battlecry: Test",
        )

    def test_safe_int(self):
        self.assertEqual(bg_review.safe_int("42"), 42)
        self.assertEqual(bg_review.safe_int("BAD", default=7), 7)
        self.assertIsNone(bg_review.safe_int_or_none("BAD"))
        self.assertEqual(bg_review.safe_int_or_none("0"), 0)

    def test_lookup_hero_name_prefers_catalog_over_log_name(self):
        en_cat = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_EN, lang="en")
        used = set()
        name = bg_review.lookup_hero_name(
            {"card_id": "BG28_HERO_801", "name": "ドクター・ホリ＝デイ"},
            en_cat["by_card_id"],
            "Unknown",
            used_card_ids=used,
        )
        self.assertEqual(name, "Doctor Holli'dae")
        self.assertIn("BG28_HERO_801", used)

        # 未登録カードはログ由来の name にフォールバックする
        fallback = bg_review.lookup_hero_name(
            {"card_id": "BG99_NEW_HERO", "name": "新ヒーロー"},
            en_cat["by_card_id"],
            "Unknown",
        )
        self.assertEqual(fallback, "新ヒーロー")

    def test_lookup_discover_source_handles_golden_suffix(self):
        en_cat = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_EN, lang="en")
        used = set()
        label = bg_review.lookup_discover_source(
            {"source_cid": "BG_Minion_02_G", "source_name": "ロデオ・パフォーマー"},
            bg_review.DISCOVER_SOURCE_LABELS_BY_LANG["en"],
            en_cat["by_card_id"],
            "Discover",
            used_card_ids=used,
        )
        self.assertEqual(label, "Rodeo Performer")
        self.assertIn("BG_Minion_02_G", used)

    def test_output_path_builders(self):
        self.assertEqual(bg_review.build_split_output_path("out.html", 2), "out_game2.html")
        self.assertEqual(bg_review.build_split_output_path("out", 1), "out_game1.html")
        self.assertEqual(bg_review.build_ai_output_path("out.html"), "out_ai.md")
        self.assertEqual(bg_review.build_ai_output_path("out.html", game_idx=3), "out_game3_ai.md")
        self.assertEqual(bg_review.build_ai_output_path("review.md", ai_only=True), "review.md")
        self.assertEqual(bg_review.build_ai_output_path("review.md", game_idx=2, ai_only=True), "review_game2.md")


class TestParserAndGenerators(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.tmp_dir.name, "Power.log")
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(build_synthetic_power_log())
        self.catalog_en = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_EN, lang="en")
        self.catalog_ja = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_JA, lang="ja")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_parse_power_log_full_flow(self):
        games = bg_review.parse_power_log(self.log_path)
        self.assertEqual(len(games), 1)
        game = games[0]

        self.assertEqual(game["hero_card_id"], "TB_BaconShop_HERO_43")
        self.assertEqual(game["final_place"], 1)
        self.assertEqual(len(game["hero_choices"]), 2)
        self.assertEqual(game["hero_choices"][0]["history"], ["TB_BaconShop_HERO_40", "TB_BaconShop_HERO_43"])
        self.assertTrue(game["hero_choices"][0]["chosen"])
        self.assertTrue(game["hero_choices"][1]["locked"])

        # 種族推定
        self.assertIn("QUILLBOAR", game["active_tribes"])
        self.assertIn("UNDEAD", game["active_tribes"])

        # ターン1検証
        t1 = game["turns"][1]
        self.assertEqual(t1["upgrade_cost_start"], 5)
        self.assertEqual(t1["gold_start"], 3)
        self.assertEqual(t1["gold_end"], 0)
        self.assertEqual(len(t1["rolls"]), 1)
        self.assertEqual(t1["rolls"][0]["offered"], ["BG_Minion_01", "BG_Minion_03"])
        self.assertEqual(t1["rolls"][0]["bought"], ["BG_Minion_01"])
        self.assertEqual(len(t1["discovers"]), 1)
        self.assertEqual(t1["discovers"][0]["source_cid"], "BG_Minion_02_G")

        # 盤面ミニオン + ATTACHED 経由の悪夢の恵み + 異常ATK無視
        self.assertEqual(len(t1["board_end"]), 1)
        self.assertEqual(t1["board_end"][0]["atk"], 3)
        self.assertTrue(t1["board_end"][0]["divine_shield"])
        self.assertEqual(t1["board_end"][0]["dark_gifts"], ["BG36_MidGameEffect_000t1"])

        # 戦闘結果（WIN +4）
        self.assertIsNotNone(t1["combat"])
        self.assertEqual(t1["combat"]["result"], "WIN")
        self.assertEqual(t1["combat"]["damage"], 4)
        self.assertEqual(len(t1["combat"]["opp_board"]), 1)

        # ターン2検証（凍結持ち越し・リロール・EOF時戦闘確定）
        t2 = game["turns"][2]
        self.assertEqual(len(t2["rolls"]), 2)
        self.assertEqual(t2["rolls"][0]["carried_over"], ["BG_Minion_03"])
        self.assertEqual(t2["rolls"][0]["offered"], ["BG_Spell_01"])
        self.assertEqual(t2["rolls"][1]["offered"], ["BG_Minion_02"])
        self.assertIsNotNone(t2["combat"])
        self.assertEqual(t2["combat"]["result"], "LOSS")
        self.assertEqual(t2["combat"]["damage"], 5)

    def test_english_outputs_have_no_japanese_hero_or_golden_discover_leaks(self):
        games = bg_review.parse_power_log(self.log_path)
        html_out = os.path.join(self.tmp_dir.name, "nested", "en_report.html")
        ai_out = os.path.join(self.tmp_dir.name, "nested", "en_report_ai.md")

        bg_review.generate_html(games, html_out, card_catalog=self.catalog_en, lang="en")
        bg_review.generate_ai_text(games, ai_out, card_catalog=self.catalog_en, lang="en")

        with open(html_out, encoding="utf-8") as f:
            html_text = f.read()
        with open(ai_out, encoding="utf-8") as f:
            ai_text = f.read()

        for text in (html.unescape(html_text), ai_text):
            self.assertIn("Dinotamer Brann", text)
            self.assertIn("Doctor Holli'dae", text)
            self.assertIn("Rodeo Performer", text)
            self.assertIn("Harpy's Talons", text)
            self.assertNotIn("恐竜使いブラン", text)
            self.assertNotIn("ドクター・ホリ＝デイ", text)
            self.assertNotIn("ロデオ・パフォーマー", text)

    def test_japanese_outputs_render_correctly(self):
        games = bg_review.parse_power_log(self.log_path)
        html_out = os.path.join(self.tmp_dir.name, "ja_report.html")
        ai_out = os.path.join(self.tmp_dir.name, "ja_report_ai.md")

        bg_review.generate_html(games, html_out, card_catalog=self.catalog_ja, lang="ja")
        bg_review.generate_ai_text(games, ai_out, card_catalog=self.catalog_ja, lang="ja")

        with open(html_out, encoding="utf-8") as f:
            html_text = f.read()
        with open(ai_out, encoding="utf-8") as f:
            ai_text = f.read()

        for text in (html_text, ai_text):
            self.assertIn("恐竜使いブラン", text)
            self.assertIn("ドクター・ホリ＝デイ", text)
            self.assertIn("ロデオ・パフォーマー", text)
            self.assertIn("ハーピーの爪", text)


class _FakeHTTPResponse:
    def __init__(self, body_bytes, headers=None):
        self._body = body_bytes
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestCatalogCache(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_cache_populated_and_reused_without_network(self):
        gz_payload = gzip.compress(json.dumps(SAMPLE_RAW_CARDS_EN).encode("utf-8"))
        fake_resp = _FakeHTTPResponse(
            gz_payload,
            headers={"Content-Encoding": "gzip", "ETag": '"v1"'},
        )
        with mock.patch("urllib.request.urlopen", return_value=fake_resp) as m_open:
            cat1 = bg_review.fetch_card_catalog(lang="en", cache_dir=self.tmp_dir.name)
            self.assertEqual(m_open.call_count, 1)
            self.assertEqual(cat1["by_card_id"]["BG28_HERO_801"]["name"], "Doctor Holli'dae")
            self.assertEqual(cat1["by_dbf_id"][300001]["name"], "Dragon Skull")

            # 2回目はキャッシュヒットしネットワークアクセスなし
            cat2 = bg_review.fetch_card_catalog(lang="en", cache_dir=self.tmp_dir.name)
            self.assertEqual(m_open.call_count, 1)
            self.assertEqual(cat2["by_card_id"]["BG28_HERO_801"]["name"], "Doctor Holli'dae")
            self.assertEqual(cat2["dark_gifts"]["BG36_MidGameEffect_000t1"][0], "Harpy's Talons")

    def test_offline_and_stale_cache_fallback(self):
        cache_path = os.path.join(self.tmp_dir.name, "cards_catalog_enUS.json.gz")
        cat = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_EN, lang="en")
        bg_review._save_catalog_cache(cache_path, cat, etag='"old-etag"')

        # オフラインモードでは TTL=0 でもキャッシュを使用しネットワークアクセスしない
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("must not call network")):
            loaded = bg_review.fetch_card_catalog(
                lang="en", offline=True, cache_dir=self.tmp_dir.name, cache_ttl=0
            )
            self.assertEqual(loaded["by_card_id"]["TB_BaconShop_HERO_43"]["name"], "Dinotamer Brann")

        # ネットワーク障害時も期限切れキャッシュにフォールバックする
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            loaded = bg_review.fetch_card_catalog(
                lang="en", cache_dir=self.tmp_dir.name, cache_ttl=0
            )
            self.assertEqual(loaded["by_card_id"]["TB_BaconShop_HERO_43"]["name"], "Dinotamer Brann")

    def test_etag_304_not_modified(self):
        cache_path = os.path.join(self.tmp_dir.name, "cards_catalog_enUS.json.gz")
        cat = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_EN, lang="en")
        bg_review._save_catalog_cache(cache_path, cat, etag='"v-etag"')

        err_304 = urllib.error.HTTPError(
            url="https://api.hearthstonejson.com/v1/latest/enUS/cards.json",
            code=304,
            msg="Not Modified",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err_304) as m_open:
            loaded = bg_review.fetch_card_catalog(
                lang="en", cache_dir=self.tmp_dir.name, cache_ttl=0
            )
            self.assertEqual(m_open.call_count, 1)
            req = m_open.call_args[0][0]
            self.assertEqual(req.get_header("If-none-match"), '"v-etag"')
            self.assertEqual(loaded["by_card_id"]["TB_BaconShop_HERO_43"]["name"], "Dinotamer Brann")

    def test_refresh_cache_bypasses_fresh_cache(self):
        cache_path = os.path.join(self.tmp_dir.name, "cards_catalog_enUS.json.gz")
        old_cat = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_EN[:1], lang="en")
        bg_review._save_catalog_cache(cache_path, old_cat, etag='"old"')

        gz_payload = gzip.compress(json.dumps(SAMPLE_RAW_CARDS_EN).encode("utf-8"))
        fake_resp = _FakeHTTPResponse(
            gz_payload,
            headers={"Content-Encoding": "gzip", "ETag": '"new"'},
        )
        with mock.patch("urllib.request.urlopen", return_value=fake_resp) as m_open:
            refreshed = bg_review.fetch_card_catalog(
                lang="en", refresh_cache=True, cache_dir=self.tmp_dir.name
            )
            self.assertEqual(m_open.call_count, 1)
            self.assertIn("BG28_HERO_801", refreshed["by_card_id"])
            req = m_open.call_args[0][0]
            self.assertIsNone(req.get_header("If-none-match"))


class TestCLIAndLogDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_find_latest_power_log_uses_env_var(self):
        d1 = os.path.join(self.tmp_dir.name, "Hearthstone_2026_01_01")
        d2 = os.path.join(self.tmp_dir.name, "Hearthstone_2026_01_02")
        os.makedirs(d1)
        os.makedirs(d2)
        p1 = os.path.join(d1, "Power.log")
        p2 = os.path.join(d2, "Power.log")
        with open(p1, "w", encoding="utf-8") as f:
            f.write("old")
        with open(p2, "w", encoding="utf-8") as f:
            f.write("new")
        os.utime(p1, (1000, 1000))
        os.utime(p2, (2000, 2000))

        with mock.patch.dict(os.environ, {"HEARTHSTONE_LOG_DIR": self.tmp_dir.name}):
            self.assertEqual(bg_review.find_latest_power_log(), p2)

    def test_explicit_missing_log_file_does_not_fallback_to_cwd(self):
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.tmp_dir.name)
            with open("Power.log", "w", encoding="utf-8") as f:
                f.write(build_synthetic_power_log())
            with self.assertRaises(SystemExit) as cm:
                bg_review.main(["nonexistent.log", "--offline"])
            self.assertEqual(cm.exception.code, 1)
        finally:
            os.chdir(orig_cwd)

    def test_cli_end_to_end_offline(self):
        log_path = os.path.join(self.tmp_dir.name, "Power.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(build_synthetic_power_log())

        cache_dir = os.path.join(self.tmp_dir.name, "cache")
        en_cat = bg_review._build_catalog_from_cards(SAMPLE_RAW_CARDS_EN, lang="en")
        bg_review._save_catalog_cache(
            os.path.join(cache_dir, "cards_catalog_enUS.json.gz"),
            en_cat,
        )

        out_html = os.path.join(self.tmp_dir.name, "out", "report.html")
        with mock.patch.dict(os.environ, {"BG_REVIEW_CACHE_DIR": cache_dir}):
            bg_review.main([log_path, "--ai-text", "--lang", "en", "--offline", "-o", out_html])

        out_ai = os.path.join(self.tmp_dir.name, "out", "report_ai.md")
        self.assertTrue(os.path.isfile(out_html))
        self.assertTrue(os.path.isfile(out_ai))
        with open(out_ai, encoding="utf-8") as f:
            ai_text = f.read()
        self.assertIn("Doctor Holli'dae", ai_text)
        self.assertNotIn("ドクター・ホリ＝デイ", ai_text)


if __name__ == "__main__":
    unittest.main()
