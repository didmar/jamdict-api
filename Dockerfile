FROM python:3.8-buster

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY download_data.sh .
RUN ./download_data.sh

COPY jamdictapi.py .
COPY run.sh .

# Pre-compute word frequency file
RUN python3 -c "from jamdictapi import gen_word_to_freqrank; gen_word_to_freqrank()"

ENTRYPOINT ["./run.sh"]
