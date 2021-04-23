import json
import re

import operator
import os
import random
import sys
from collections import defaultdict
from itertools import chain
from typing import List, Optional

import romkan
from chirptext.deko import HIRAGANA, KATAKANA
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jamdict import Jamdict
from contextvars import ContextVar

# Wrapping Jamdict in a ContextVar for SQLite access (not multi-threaded...)
JMD = Jamdict()
_JMD = ContextVar('JMD', default=JMD)


async def coro_jmd():
    return _JMD.get()


if not os.path.exists('data'):
    os.mkdir('data')

WORDS_FREQ_FILEPATH = "data/nf_words_freq"

KANJI_JSON_FILE = "data/kanji-jouyou.json"


def parse_kanji_json_file():
    with open(KANJI_JSON_FILE) as infile:
        return json.load(infile)


KANJIS = parse_kanji_json_file()


def generate_kanjis_by_jlpt():
    kanjis_by_jlpt = defaultdict(set)
    for kanji, details in KANJIS.items():
        kanjis_by_jlpt[details["jlpt_new"]].add(kanji)
    return kanjis_by_jlpt


KANJIS_BY_JLPT = generate_kanjis_by_jlpt()
MIN_JLPT_LEVEL = 1
MAX_JLPT_LEVEL = 5


def generate_word_frequency_file(filepath):
    print("Generating word frequency file, can take a few minutes...")
    nf_to_kanjis = defaultdict(set)
    # Hackish way to get all the JMdict entries through jamdict's internal db
    # (Doing this to not have to download JMdict separately as an XML file)
    with JMD.jmdict.ctx() as ctx:
        for _entry in JMD.jmdict.Entry.select(ctx=ctx):
            idseq = _entry.idseq
            entry = JMD.jmdict.get_entry(idseq, ctx=ctx)
            if entry:
                for word in chain(entry.kanji_forms, entry.kana_forms):
                    for pri in word.pri:
                        if pri.startswith('nf'):
                            nf_x = int(pri[-2:])
                            nf_to_kanjis[nf_x].add(word.text)

    with open(filepath, "w") as outfile:
        for nf_x in sorted(nf_to_kanjis.keys()):
            for word in nf_to_kanjis[nf_x]:
                print(word, file=outfile)


def gen_word_to_freqrank():
    if not os.path.exists(WORDS_FREQ_FILEPATH):
        generate_word_frequency_file(WORDS_FREQ_FILEPATH)

    _word_to_freqrank = {}
    with open(WORDS_FREQ_FILEPATH) as infile:
        for idx, line in enumerate(infile):
            word = line.rstrip()
            _word_to_freqrank[word] = idx

    return _word_to_freqrank


WORD_TO_FREQRANK = gen_word_to_freqrank()


def word_to_freqrank(word):
    return WORD_TO_FREQRANK.get(word, sys.maxsize)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/to-hiragana/{word}")
def to_hiragana(word: str):
    _word = word.lower()
    hiragana = romkan.to_hiragana(_word)
    valid = not re.search("[a-z']", hiragana)

    if hiragana.endswith("ん") and not (_word.endswith("nn") or _word.endswith("'")):
        partial = hiragana[:-1] + "n"
    else:
        partial = hiragana

    return {
        'hiragana': hiragana,
        'partial': partial,
        'valid': valid,
    }


@app.get("/word-details/{word}")
async def lookup_word(word: str):
    jmd = await coro_jmd()
    lookup_res = jmd.lookup(word, strict_lookup=True, lookup_chars=False)
    if not lookup_res.entries:
        raise Exception(f"No entry found for {word} !")
    entry = lookup_res.entries[0]
    return {
        "meaning": entry.senses[0].text(),
        "freqrank": word_to_freqrank(word),
    }


@app.get("/lookup-words/{hiragana}")
async def lookup_word_entries(
        hiragana: str,
        kanji_to_match: str = None,
        min_length: int = 1,
        min_nb_kanjis: int = 1,
):
    valid_entries = []
    errors = []

    jmd = await coro_jmd()
    lookup_res = jmd.lookup(hiragana, strict_lookup=True, lookup_chars=False)
    print(f"Lookup result for {hiragana}:")
    for entry in lookup_res.entries:
        for kanji_form in entry.kanji_forms:
            word = str(kanji_form)
            is_valid, error = valid_word_candidate(word, kanji_to_match, min_length, min_nb_kanjis)
            if is_valid:
                json_entry = word_entry_to_custom_json(word, entry)
                valid_entries.append(json_entry)
                print(f"- {word}: OK")
                break
            else:
                print(f"- {word}: {error}")
                errors.append(error)

    return {
        "valid_entries": valid_entries,
        "errors": errors,
    }


def valid_word_candidate(
        word: str,
        kanji_to_match: Optional[str],
        min_length: int,
        min_nb_kanjis: int,
        min_jlpt: int = MIN_JLPT_LEVEL,
):
    if kanji_to_match and kanji_to_match not in word:
        return False, f'3 Word must contain {kanji_to_match}'
    if len(word) < min_length:
        return False, f'2 Word must be {min_length}+ character'

    kanjis = get_word_kanjis_gte_min_jlpt(word, min_jlpt)

    if len(kanjis) < min_nb_kanjis:
        return False, f'1 Word must contain {min_nb_kanjis}+ kanji'

    return True, None


@app.get("/word-meaning/{word}")
async def get_word_meaning(word: str):
    jmd = await coro_jmd()
    lookup_res = jmd.lookup(word, strict_lookup=True, lookup_chars=False)
    if not lookup_res.entries:
        raise Exception(f"No entry found for {word} !")
    entry = lookup_res.entries[0]
    return {
        "meaning": entry.senses[0].text()
    }


@app.get("/find-word-with-kanji/{kanji_to_match}")
@app.post("/find-word-with-kanji/{kanji_to_match}")
async def find_one_valid_word(
        kanji_to_match: str,
        candidate_kanjis_only: bool = True,
        excluded_words: List[str] = None,
        excluded_kanjis: List[str] = None,
        min_length: int = 1,
        min_nb_kanjis: int = 1,
        min_jlpt: int = MIN_JLPT_LEVEL,
        pool_size: int = 3,
):
    if excluded_words is None:
        excluded_words = []
    if excluded_kanjis is None:
        excluded_kanjis = []

    candidate_words_to_entry = {}
    query = f"%{kanji_to_match}%"
    jmd = await coro_jmd()
    lookup_res = jmd.lookup(query, strict_lookup=True, lookup_chars=False)
    for entry in lookup_res.entries:
        for kanji_form in entry.kanji_forms:
            word = str(kanji_form)
            if word in excluded_words:
                continue
            is_valid, _ = valid_word_candidate(word, kanji_to_match, min_length, min_nb_kanjis,
                                               min_jlpt=min_jlpt)
            if is_valid:
                # Avoid kanjis that are not outside our grade, or excluded
                if (
                        candidate_kanjis_only is False
                        or (all_kanjis_lte_max_grad(word, min_jlpt)
                            and not any((char in excluded_kanjis for char in word)))
                ):
                    print(f"{word} is a candidate")
                    candidate_words_to_entry[word] = entry

    if candidate_words_to_entry:
        print(f"Found {len(candidate_words_to_entry)} possible words for {kanji_to_match}")
        word_freqrank_pairs = []
        for word in candidate_words_to_entry.keys():
            freqrank = word_to_freqrank(word)
            if freqrank != sys.maxsize:
                word_freqrank_pairs.append((word, freqrank))

        if word_freqrank_pairs:
            sorted_words = sorted(word_freqrank_pairs, key=operator.itemgetter(1))
            for word, freqrank in sorted_words[:10]:
                print(f"- {word} ({freqrank})")
            # Randomize a bit
            word = random.choice(sorted_words[:pool_size])[0]
        else:
            word = random.choice(list(candidate_words_to_entry.keys()))

        entry = candidate_words_to_entry[word]
        result = word_entry_to_custom_json(word, entry)
        return {
            "result": result,
        }

    return {
        "result": None
    }


def word_entry_to_custom_json(word, entry):
    json_entry = entry.to_json()
    json_entry["word"] = word
    json_entry["kanjis"] = list(kanji_list_from_word_entry(json_entry))
    return json_entry


def kanji_list_from_word_entry(result):
    kanjis = set()
    has_unknown_char = False
    if result["kanji"]:
        for idx, kanji_entry in enumerate(result["kanji"]):
            text = kanji_entry["text"]
            for c in text:
                if c not in HIRAGANA and c not in KATAKANA:
                    if c in KANJIS:
                        kanjis.add(c)
                    else:
                        # for example, first entry for 三密 is ３密 !
                        # we want to skip it and use the correct second entry
                        has_unknown_char = True
                        break
            if has_unknown_char:
                kanjis = set()
                has_unknown_char = False
            else:
                break
    if has_unknown_char:
        raise Exception(f"No valid kanji entry found for {result}")
    return list(kanjis)


async def all_kanjis_lte_max_grad(word: str, min_jlpt: int):
    for kanji in word:
        grade_ok = await is_gte_min_jlpt(kanji, min_jlpt)
        if not grade_ok:
            return False
    return True


async def is_gte_min_jlpt(kanji: str, min_jlpt: int):
    entry = KANJIS_BY_JLPT.get(kanji)
    if entry is None:
        return False
    return entry["jlpt_new"] >= min_jlpt


def get_word_kanjis_gte_min_jlpt(word: str, min_jlpt: int):
    kanjis = []
    for char in word:
        if is_gte_min_jlpt(char, min_jlpt):
            kanjis.append(char)
    return kanjis


@app.get("/kanjis")
def get_kanjis(min_jlpt: int = 1, max_jlpt: int = 5):
    kanjis = set()
    if min_jlpt > max_jlpt:
        min_jlpt, max_jlpt = max_jlpt, min_jlpt
    for grade in range(min_jlpt, max_jlpt + 1):
        kanjis.update(KANJIS_BY_JLPT[grade])
    return {
        "kanjis": [kanji_details(kanji) for kanji in kanjis]
    }


@app.get("/kanji-details/{kanji}")
def kanji_details(kanji: str):
    entry = KANJIS.get(kanji)
    if not entry:
        raise Exception(f"Kanji {kanji} not found in Jouyou kanjis list !")
    meaning = ", ".join(entry["meanings"])
    jlpt = entry["jlpt_new"]
    return {
        "kanji": kanji,
        "meaning": meaning,
        "jlpt": jlpt,
    }
