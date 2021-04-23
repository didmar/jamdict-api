Jamdict API
============

API for Japanese language study, based on [Jamdict](https://github.com/neocl/jamdict) library.

Added some useful routes for my project [Kanji game](https://github.com/didmar/kanjigame-elm)

How to install
---------------

The easiest way is to use the provided Dockerfile:
```
make docker
docker run -p 127.0.0.1:9000:9000 jamdictapi:latest
```

Otherwise, to build locally on a Ubuntu/Debian machine (tested with Ubuntu 20.04):

First install Python >=3.7, PIP and required dependencies
```sh
sudo apt install python3.7-dev python3-pip
python3.7 -m pip install pip
python3 -m pip install -r requirements.txt --user
```

Run the following script to download required data files
```sh
./download_data.sh
```

Finally run this script to start the API
```sh
./run.sh
```

Go to [http://127.0.0.1:9000/docs](http://127.0.0.1:9000/docs) to check the documentation.
