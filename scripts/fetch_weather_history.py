"""
fetch_weather_history.py — per-game weather text from nflverse play-by-play.

nflverse schedules carry temperature and wind but not precipitation. The
play-by-play file carries the gamebook's weather line ("Rain Temp: 45° F,
Humidity: 90%, Wind: NW 12 mph"), which is the only historical rain/snow
record available for free. One small parquet per run, game-level.

    .venv/bin/python -W ignore scripts/fetch_weather_history.py 2016 2025
"""
import sys
sys.path.insert(0, 'src')
import pandas as pd
from nflmodel.config import CACHE_DIR
from nflmodel.data import PBP_URL

a, b = int(sys.argv[1]), int(sys.argv[2])
frames = []
for s in range(a, b + 1):
    df = pd.read_parquet(PBP_URL.format(season=s),
                         columns=['game_id', 'weather', 'roof', 'temp', 'wind'])
    g = df.groupby('game_id').first().reset_index()
    g['season'] = s
    frames.append(g)
    print(s, len(g), g.weather.notna().mean().round(3), flush=True)
out = pd.concat(frames, ignore_index=True)
out.to_parquet(CACHE_DIR / f'weather_{a}_{b}.parquet', index=False)
print('wrote', CACHE_DIR / f'weather_{a}_{b}.parquet')
