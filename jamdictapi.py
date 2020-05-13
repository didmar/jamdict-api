import re

import operator
import os
import pickle
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


def generate_word_frequency_file(filepath):
    print("Generating word frequency file...")
    nf_to_kanjis = defaultdict(set)
    for entry in JMD.jmdict_xml.entries:
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


# 1-6 for primary school, 8 for secondary school
KANJI_GRADE_TO_INFO = {
    1: {"desc": "教育第１学年", "score": 1},
    2: {"desc": "教育第２学年", "score": 2},
    3: {"desc": "教育第３学年", "score": 3},
    4: {"desc": "教育第４学年", "score": 4},
    5: {"desc": "教育第５学年", "score": 5},
    6: {"desc": "教育第６学年", "score": 6},
    8: {"desc": "常用", "score": 7},
}
KANJI_GRADES = sorted(KANJI_GRADE_TO_INFO.keys())
MAX_KANJI_GRADE = KANJI_GRADES[-1]

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
    return {
        'hiragana': hiragana,
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
        max_kanji_grade: int = MAX_KANJI_GRADE,
):
    if kanji_to_match and kanji_to_match not in word:
        return False, f'3 Word must contain {kanji_to_match}'
    if len(word) < min_length:
        return False, f'2 Word must be {min_length}+ character'

    kanjis = get_word_kanjis_lte_max_grade(word, max_kanji_grade)

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


@app.get("/kanji-details/{kanji}")
async def kanji_details(kanji: str):
    jmd = await coro_jmd()
    entry = jmd.get_char(kanji)
    meaning = ", ".join((m.value for m in entry.rm_groups[0].meanings if m.m_lang == ''))
    grade = int(entry.grade) if entry.grade else None
    return {
        "kanji": kanji,
        "meaning": meaning,
        "grade": grade,
    }


@app.get("/find-word-with-kanji/{kanji_to_match}")
async def find_one_valid_word(
        kanji_to_match: str,
        candidate_kanjis_only: bool = True,
        excluded_words: List[str] = None,
        excluded_kanjis: List[str] = None,
        min_length: int = 1,
        min_nb_kanjis: int = 1,
        max_kanji_grade: int = MAX_KANJI_GRADE,
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
                                               max_kanji_grade=max_kanji_grade)
            if is_valid:
                # Avoid kanjis that are not outside our grade, or excluded
                if (
                        candidate_kanjis_only is False
                        or (all_kanjis_lte_max_grad(word, max_kanji_grade)
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
    if result["kanji"]:
        for c in result["kanji"][0]["text"]:
            if c not in HIRAGANA and c not in KATAKANA:
                kanjis.add(c)
    return list(kanjis)

async def all_kanjis_lte_max_grad(word, max_kanji_grade):
    for kanji in word:
        grade_ok = await is_lte_max_grade(kanji, max_kanji_grade)
        if not grade_ok:
            return False
    return True


async def is_lte_max_grade(kanji: str, max_kanji_grade: int):
    jmd = await coro_jmd()
    entry = jmd.get_char(kanji)
    if entry.grade:
        return int(entry.grade) <= max_kanji_grade
    return False


def get_word_kanjis_lte_max_grade(word: str, max_kanji_grade: int):
    kanjis = []
    for char in word:
        if is_lte_max_grade(char, max_kanji_grade):
            kanjis.append(char)
    return kanjis


def grade_text(grade):
    if grade is None:
        return f"No grade"
    info = KANJI_GRADE_TO_INFO.get(grade)
    if info:
        return f'{info["score"] * "★"} {info["desc"]}'
    raise Exception(f"Grade {grade} is not used in the game !")


def next_grade(grade):
    idx = KANJI_GRADES.index(grade)
    if idx == len(KANJI_GRADES) - 1:
        return idx
    return idx + 1


def kanjis_by_grade():
    def compute_kanjis_by_grade():
        __kanjis_by_grade = defaultdict(set)
        for kanji in JMD.kd2_xml.char_map.values():
            if kanji.grade is not None:
                __kanjis_by_grade[int(kanji.grade)].add(kanji.literal)
        return __kanjis_by_grade

    cache_filepath = "data/kanjis_grade"

    if os.path.isfile(cache_filepath):
        print("Loading kanjis from cache")
        with open(cache_filepath, "rb") as cache_file:
            _kanjis_by_grade = pickle.load(cache_file)

    else:
        print("Save kanjis to cache")
        _kanjis_by_grade = compute_kanjis_by_grade()
        with open(cache_filepath, "wb") as cache_file:
            pickle.dump(_kanjis_by_grade, cache_file)

    return _kanjis_by_grade


KANJIS_BY_GRADE = kanjis_by_grade()


@app.get("/kanjis")
def get_kanjis(min_grade: int = 1, max_grade: int = MAX_KANJI_GRADE):
    kanjis = []
    for grade in range(min_grade, max_grade + 1):
        kanjis.extend(KANJIS_BY_GRADE[grade])
    return {
        "kanjis": kanjis,
    }
