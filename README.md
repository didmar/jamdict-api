Jamdict API
============

API to use [Jamdict](https://github.com/neocl/jamdict) library.

Added some useful routes for my project [Kanji game](https://github.com/didmar/kanjigame-elm)

How to install
---------------

Instructions for Ubuntu 18.04 

Install Python >=3.7, PIP and required dependencies:
```sh
sudo apt install python3.7-dev python3-pip
python3.7 -m pip install pip
python3 -m pip install -r requirements.txt --user
```

Run the following script to download the dictionary files and import them
```sh
./download_dicts.sh
```

Run the API:
```sh
./run.sh
```