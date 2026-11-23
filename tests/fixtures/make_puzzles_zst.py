"""Writes tests/fixtures/puzzles_small.csv.zst (FIX-B6 B): six rows in Lichess's puzzle CSV format,
compressed with Zstandard in two frames. Four are kept by the import's filters (one has NbPlays 10,
one a negative Popularity). The ids are made up.

    .venv/bin/python tests/fixtures/make_puzzles_zst.py
"""

import sys
from compression import zstd
from pathlib import Path
# Columns in Lichess's order, with a real mate-in-1 and a few varied rows; ids are made up.
header = "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags"
rows = [
    "zA001,r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3,g8f6 h5f7,820,80,95,1000,mate mateIn1 short,,Italian_Game",
    "zA002,rnbqkbnr/ppppp1pp/8/5p2/4P3/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 2,e4f5 d8h4,840,85,90,800,advantage short,,",
    "zA003,6k1/5ppp/8/8/7p/8/8/R3R2K b - - 0 1,h4h3 a1a8,1500,75,88,500,mate mateIn1 backRankMate,,",
    "zA004,8/8/8/8/8/8/8/K6k w - - 0 1,a1a2 h1h2,900,90,90,10,endgame,,",
    "zA005,8/8/8/8/8/8/8/K6k w - - 0 1,a1a2 h1h2,1900,90,-5,600,endgame,,",
    "zA006,6k1/5ppp/8/8/7p/8/8/R3R2K b - - 0 1,h4h3 e1e8,1600,77,80,300,mate mateIn1 fork,,",
]
data = (header + "\n" + "\n".join(rows) + "\n").encode()
# two frames, as a stream compressed in parts may have
half = len(data) // 2
(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('puzzles_small.csv.zst')).write_bytes(zstd.compress(data[:half]) + zstd.compress(data[half:]))
