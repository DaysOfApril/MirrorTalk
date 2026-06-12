#!/bin/bash
cd "d:/AI/My-projects/Tmp/MirrorTalk/backend"
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
