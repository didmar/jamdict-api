#!/bin/bash
set -e

DATAFOLDER="$HOME/.jamdict/data"
mkdir -p $DATAFOLDER

wget -O $DATAFOLDER/JMdict_e.gz http://ftp.monash.edu/pub/nihongo/JMdict_e.gz
wget -O $DATAFOLDER/kanjidic2.xml.gz http://www.edrdg.org/kanjidic/kanjidic2.xml.gz

python3 -m jamdict.tools import
