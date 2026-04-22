# SsupWoofer

A python script to route low frequencies to a bluetooth speaker and high frequencies to your laptop speakers. Basically turns any random BT speaker into a 2.1 subwoofer setup.

## requirements
- python 3
- `pip install -r requirements.txt`
- VB-Audio Virtual Cable (the app has a button to install it probably, if it doesnt show, download from vb-audio website, run the setup as admin, restart)

## how to use
1. Run `python ssup_woofer_app.py`
2. Select your virtual cable input, main speakers, and subwoofer.
3. Tweak the crossover and delay until it sounds good.
4. Click Start.

## notes
- Delay slider is to sync up bluetooth lag (usually around 1500-2000ms).
- Sub gain uses a tanh curve so it clips nicely instead of breaking your speakers.
