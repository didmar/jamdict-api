#!/bin/bash

python3 -m uvicorn jamdictapi:app --reload --host 0.0.0.0 --port 9000
