#!/bin/bash
set -e

mkdir -p data
wget -O data/kanji-jouyou.json https://github.com/davidluzgouveia/kanji-data/raw/master/kanji-jouyou.json
