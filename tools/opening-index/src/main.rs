//! Opening data pipeline, stage 0 (OPENING_DATA_PROMPT.md).
//!
//! Streams a Lichess PGN dump on stdin and builds a position index: one record per
//! (position, move, rating band of the mover, time-control class), carrying the game
//! count, the result split and the shallowest ply it was seen at. Dimensioned, not
//! filtered: band and time control are key columns, so any later question is a query.
//!
//!   zstdcat DUMP | opening-index scan  --out DIR [--chunk-games N] [--ply-cap P] [--workers W]
//!   opening-index merge  --out FILE RUN...
//!   opening-index stats  --index FILE
//!   opening-index book   --index FILE --out FILE.bin [--min-games N] [--bands 1-3] [--speeds 1,2,3]
//!   opening-index hashes --games N        (stdin PGN → FEN, key, move per ply, for checking)
//!   opening-index fens   --targets FILE --out FILE [--max-ply P]  (stdin PGN → key, FEN per target)
//!
//! Aggregation is disk-backed. Each chunk of games is aggregated in memory by the
//! workers, sorted and written as one run; a chunk with a DONE marker is skipped on
//! restart, so a run that dies resumes at its last complete chunk. Runs are combined
//! by a streaming k-way merge into a per-month index, and months combine the same way,
//! so adding a month never reprocesses another.

use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::ops::ControlFlow;
use std::path::{Path, PathBuf};
use std::time::Instant;

use pgn_reader::shakmaty::{
    Chess, EnPassantMode, Move, Position, Role, Square, fen::Fen, san::San,
    zobrist::{Zobrist64, ZobristHash},
};
use pgn_reader::{RawTag, Reader, SanPlus, Visitor};
use rustc_hash::FxHashMap;

// ── Dimensions ───────────────────────────────────────────────────────────────

/// Mover's rating, 200-point bands: 0 is under 600, 1 is 600–799 … 11 is 2600+.
/// 15 is unknown.
pub const BANDS: usize = 12;
fn band_of(elo: u16) -> u8 {
    if elo == 0 {
        return 15;
    }
    ((elo as i32 - 400) / 200).clamp(0, 11) as u8
}

/// Lichess's own speed classes, from estimated duration = base + 40 × increment.
pub const SPEEDS: [&str; 6] = ["ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence"];
fn speed_of(tc: &[u8]) -> u8 {
    if tc == b"-" {
        return 5;
    }
    let s = std::str::from_utf8(tc).unwrap_or("");
    let mut it = s.split('+');
    let base: u32 = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
    let inc: u32 = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
    let est = base + 40 * inc;
    match est {
        e if e < 30 => 0,
        e if e < 180 => 1,
        e if e < 480 => 2,
        e if e < 1500 => 3,
        _ => 4,
    }
}

// ── Records ──────────────────────────────────────────────────────────────────

/// 24 bytes on disk, little-endian, sorted by (key, mv, dims).
#[derive(Clone, Copy, Default, Debug)]
struct Rec {
    key: u64,
    mv: u16,
    dims: u8, // band << 3 | speed
    minply: u8,
    n: u32,
    w: u32, // white wins
    d: u32, // draws
}
const REC: usize = 24;

impl Rec {
    fn sort_key(&self) -> (u64, u16, u8) {
        (self.key, self.mv, self.dims)
    }
    fn write(&self, out: &mut impl Write) -> io::Result<()> {
        let mut b = [0u8; REC];
        b[0..8].copy_from_slice(&self.key.to_le_bytes());
        b[8..10].copy_from_slice(&self.mv.to_le_bytes());
        b[10] = self.dims;
        b[11] = self.minply;
        b[12..16].copy_from_slice(&self.n.to_le_bytes());
        b[16..20].copy_from_slice(&self.w.to_le_bytes());
        b[20..24].copy_from_slice(&self.d.to_le_bytes());
        out.write_all(&b)
    }
    fn read(inp: &mut impl Read) -> io::Result<Option<Rec>> {
        let mut b = [0u8; REC];
        match inp.read_exact(&mut b) {
            Ok(()) => {}
            Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
            Err(e) => return Err(e),
        }
        Ok(Some(Rec {
            key: u64::from_le_bytes(b[0..8].try_into().unwrap()),
            mv: u16::from_le_bytes(b[8..10].try_into().unwrap()),
            dims: b[10],
            minply: b[11],
            n: u32::from_le_bytes(b[12..16].try_into().unwrap()),
            w: u32::from_le_bytes(b[16..20].try_into().unwrap()),
            d: u32::from_le_bytes(b[20..24].try_into().unwrap()),
        }))
    }
    fn absorb(&mut self, o: &Rec) {
        self.n += o.n;
        self.w += o.w;
        self.d += o.d;
        self.minply = self.minply.min(o.minply);
    }
}

/// Polyglot move encoding: to square in bits 0–5, from square in 6–11, promotion in
/// 12–14 (knight 1 … queen 4). Castling is king-takes-own-rook, as Polyglot has it,
/// which is how shakmaty already represents a castling move.
fn polyglot_move(m: &Move) -> u16 {
    let from = m.from().map(sq).unwrap_or(0);
    let to = sq(m.to());
    let promo = match m.promotion() {
        Some(Role::Knight) => 1,
        Some(Role::Bishop) => 2,
        Some(Role::Rook) => 3,
        Some(Role::Queen) => 4,
        _ => 0,
    };
    to | (from << 6) | (promo << 12)
}
fn sq(s: Square) -> u16 {
    u32::from(s) as u16
}
/// The e.p. file is hashed whenever a pawn stands ready to capture, legal or not: the
/// original Polyglot rule, and python-chess's (`ZobristHasher.hash_ep_square`), which is
/// what the trainer probes with. `Legal` differed on 10 of 1.34M replayed positions — a
/// pinned capturer (review/scratch/opening_data/zobrist_check.out).
fn key_of(pos: &Chess) -> u64 {
    pos.zobrist_hash::<Zobrist64>(EnPassantMode::PseudoLegal).0
}

// ── PGN visitor: headers and the first `cap` moves, nothing else ─────────────

#[derive(Default)]
struct Game {
    welo: u16,
    belo: u16,
    speed: u8,
    result: u8, // 0 white, 1 black, 2 draw, 3 unknown
    has_fen: bool,
    sans: Vec<San>,
    reached_cap: bool,
    /// `[%eval]` after each move, White's view: centipawns, or ±(100000 − n) for mate in n.
    /// `NO_EVAL` where the move has none. Filled only when the visitor wants evals.
    evals: Vec<i32>,
    /// The family part of the `Opening` header (before the colon); filled only with evals.
    family: String,
}

const NO_EVAL: i32 = i32::MIN;

struct Collect {
    cap: usize,
    want_evals: bool,
}

fn parse_eval(comment: &[u8]) -> Option<i32> {
    let i = comment.windows(7).position(|w| w == b"[%eval ")?;
    let rest = &comment[i + 7..];
    let end = rest.iter().position(|&c| c == b']' || c == b' ')?;
    let v = std::str::from_utf8(&rest[..end]).ok()?;
    if let Some(m) = v.strip_prefix('#') {
        let n: i32 = m.parse().ok()?;
        return Some(if n >= 0 { 100_000 - n } else { -100_000 - n });
    }
    let x: f64 = v.parse().ok()?;
    Some((x * 100.0).round() as i32)
}

impl Visitor for Collect {
    type Tags = Game;
    type Movetext = Game;
    type Output = Game;

    fn begin_tags(&mut self) -> ControlFlow<Game, Game> {
        ControlFlow::Continue(Game { result: 3, ..Game::default() })
    }
    fn tag(&mut self, g: &mut Game, name: &[u8], value: RawTag<'_>) -> ControlFlow<Game> {
        let v = value.as_bytes();
        match name {
            b"WhiteElo" => g.welo = std::str::from_utf8(v).ok().and_then(|s| s.parse().ok()).unwrap_or(0),
            b"BlackElo" => g.belo = std::str::from_utf8(v).ok().and_then(|s| s.parse().ok()).unwrap_or(0),
            b"TimeControl" => g.speed = speed_of(v),
            b"Result" => {
                g.result = match v {
                    b"1-0" => 0,
                    b"0-1" => 1,
                    b"1/2-1/2" => 2,
                    _ => 3,
                }
            }
            b"FEN" => g.has_fen = true,
            b"Opening" if self.want_evals => {
                let v = String::from_utf8_lossy(v);
                g.family = v.split(':').next().unwrap_or("").trim().to_string();
            }
            _ => {}
        }
        ControlFlow::Continue(())
    }
    fn begin_movetext(&mut self, g: Game) -> ControlFlow<Game, Game> {
        if g.has_fen {
            return ControlFlow::Break(g);
        }
        ControlFlow::Continue(Game { sans: Vec::with_capacity(self.cap), ..g })
    }
    fn san(&mut self, g: &mut Game, san_plus: SanPlus) -> ControlFlow<Game> {
        g.sans.push(san_plus.san);
        if self.want_evals {
            g.evals.push(NO_EVAL);
        }
        if g.sans.len() < self.cap {
            ControlFlow::Continue(())
        } else {
            // At the cap: the rest of the game is skipped unparsed.
            g.reached_cap = true;
            ControlFlow::Break(std::mem::take(g))
        }
    }
    fn comment(&mut self, g: &mut Game, comment: pgn_reader::RawComment<'_>) -> ControlFlow<Game> {
        if self.want_evals {
            if let (Some(last), Some(e)) = (g.evals.last_mut(), parse_eval(comment.as_bytes())) {
                *last = e;
            }
        }
        ControlFlow::Continue(())
    }
    fn end_game(&mut self, g: Game) -> Game {
        g
    }
}

// ── Counters ─────────────────────────────────────────────────────────────────

#[derive(Default, Clone)]
struct Counts {
    games: u64,
    skipped_fen: u64,
    skipped_result: u64,
    illegal: u64,
    no_moves: u64,
    reached_cap: u64,
    observations: u64,
    games_by_speed: [u64; 6],
    players_by_band: [u64; 16],
}

impl Counts {
    fn add(&mut self, o: &Counts) {
        self.games += o.games;
        self.skipped_fen += o.skipped_fen;
        self.skipped_result += o.skipped_result;
        self.illegal += o.illegal;
        self.no_moves += o.no_moves;
        self.reached_cap += o.reached_cap;
        self.observations += o.observations;
        for i in 0..6 {
            self.games_by_speed[i] += o.games_by_speed[i];
        }
        for i in 0..16 {
            self.players_by_band[i] += o.players_by_band[i];
        }
    }
    fn to_text(&self) -> String {
        let sp: Vec<String> = SPEEDS.iter().zip(self.games_by_speed).map(|(s, n)| format!("{s}={n}")).collect();
        let bd: Vec<String> = (0..16).filter(|&i| self.players_by_band[i] > 0).map(|i| format!("{i}={}", self.players_by_band[i])).collect();
        format!(
            "games {}\nskipped_fen {}\nskipped_result {}\nillegal {}\nno_moves {}\nreached_cap {}\nobservations {}\ngames_by_speed {}\nplayers_by_band {}\n",
            self.games, self.skipped_fen, self.skipped_result, self.illegal, self.no_moves,
            self.reached_cap, self.observations, sp.join(" "), bd.join(" ")
        )
    }
    fn from_text(t: &str) -> Counts {
        let mut c = Counts::default();
        for line in t.lines() {
            let (k, v) = line.split_once(' ').unwrap_or((line, ""));
            let num = || v.parse::<u64>().unwrap_or(0);
            match k {
                "games" => c.games = num(),
                "skipped_fen" => c.skipped_fen = num(),
                "skipped_result" => c.skipped_result = num(),
                "illegal" => c.illegal = num(),
                "no_moves" => c.no_moves = num(),
                "reached_cap" => c.reached_cap = num(),
                "observations" => c.observations = num(),
                "games_by_speed" => {
                    for kv in v.split(' ') {
                        if let Some((s, n)) = kv.split_once('=') {
                            if let Some(i) = SPEEDS.iter().position(|x| *x == s) {
                                c.games_by_speed[i] = n.parse().unwrap_or(0);
                            }
                        }
                    }
                }
                "players_by_band" => {
                    for kv in v.split(' ') {
                        if let Some((i, n)) = kv.split_once('=') {
                            c.players_by_band[i.parse::<usize>().unwrap_or(15)] = n.parse().unwrap_or(0);
                        }
                    }
                }
                _ => {}
            }
        }
        c
    }
}

// ── scan ─────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Default)]
struct Val {
    n: u32,
    w: u32,
    d: u32,
    minply: u8,
}

fn play_game(g: &Game, map: &mut FxHashMap<(u64, u16, u8), Val>, c: &mut Counts) {
    c.games += 1;
    if g.has_fen {
        c.skipped_fen += 1;
        return;
    }
    if g.result == 3 {
        c.skipped_result += 1;
        return;
    }
    c.games_by_speed[g.speed as usize] += 1;
    c.players_by_band[band_of(g.welo) as usize] += 1;
    c.players_by_band[band_of(g.belo) as usize] += 1;
    if g.sans.is_empty() {
        c.no_moves += 1;
        return;
    }
    if g.reached_cap {
        c.reached_cap += 1;
    }
    let mut pos = Chess::default();
    for (ply, san) in g.sans.iter().enumerate() {
        let m = match san.to_move(&pos) {
            Ok(m) => m,
            Err(_) => {
                c.illegal += 1;
                return;
            }
        };
        let elo = if ply % 2 == 0 { g.welo } else { g.belo };
        let dims = (band_of(elo) << 3) | g.speed;
        let v = map.entry((key_of(&pos), polyglot_move(&m), dims)).or_insert(Val { minply: u8::MAX, ..Val::default() });
        v.n += 1;
        v.w += (g.result == 0) as u32;
        v.d += (g.result == 2) as u32;
        v.minply = v.minply.min(ply as u8);
        c.observations += 1;
        pos.play_unchecked(m);
    }
}

fn write_sorted(map: FxHashMap<(u64, u16, u8), Val>, path: &Path) -> io::Result<u64> {
    let mut v: Vec<Rec> = map
        .into_iter()
        .map(|((key, mv, dims), x)| Rec { key, mv, dims, minply: x.minply, n: x.n, w: x.w, d: x.d })
        .collect();
    v.sort_unstable_by_key(|r| r.sort_key());
    let mut out = BufWriter::with_capacity(1 << 20, File::create(path)?);
    for r in &v {
        r.write(&mut out)?;
    }
    out.flush()?;
    Ok(v.len() as u64)
}

fn arg<'a>(args: &'a [String], name: &str) -> Option<&'a str> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).map(|s| s.as_str())
}

fn scan(args: &[String]) -> io::Result<()> {
    let out = PathBuf::from(arg(args, "--out").expect("--out DIR"));
    let chunk_games: u64 = arg(args, "--chunk-games").map(|s| s.parse().unwrap()).unwrap_or(2_000_000);
    let cap: usize = arg(args, "--ply-cap").map(|s| s.parse().unwrap()).unwrap_or(30);
    let workers: usize = arg(args, "--workers").map(|s| s.parse().unwrap()).unwrap_or(8);
    let max_games: u64 = arg(args, "--max-games").map(|s| s.parse().unwrap()).unwrap_or(u64::MAX);
    fs::create_dir_all(&out)?;
    let stdin = io::stdin().lock();
    let mut reader = Reader::new(BufReader::with_capacity(1 << 22, stdin));
    let mut collect = Collect { cap, want_evals: false };
    let t0 = Instant::now();
    let mut chunk = 0u64;
    let mut seen = 0u64;
    loop {
        let dir = out.join(format!("chunk-{chunk:05}"));
        let done = dir.join("DONE");
        let budget = chunk_games.min(max_games.saturating_sub(seen));
        if budget == 0 {
            break;
        }
        if done.exists() {
            // Resume: this chunk is already on disk. Skip its games unparsed.
            let mut k = 0;
            while k < budget && reader.skip_game()? {
                k += 1;
            }
            seen += k;
            eprintln!("chunk {chunk}: done earlier, skipped {k} games");
            if k < budget {
                break;
            }
            chunk += 1;
            continue;
        }
        if dir.exists() {
            fs::remove_dir_all(&dir)?; // a partial chunk from a run that died
        }
        fs::create_dir_all(&dir)?;
        let tc = Instant::now();
        let (send, recv) = crossbeam_channel::bounded::<Vec<Game>>(64);
        let mut read = 0u64;
        let results: Vec<(FxHashMap<(u64, u16, u8), Val>, Counts)> = std::thread::scope(|s| {
            let hs: Vec<_> = (0..workers)
                .map(|_| {
                    let recv = recv.clone();
                    s.spawn(move || {
                        let mut map: FxHashMap<(u64, u16, u8), Val> = FxHashMap::default();
                        let mut c = Counts::default();
                        for batch in recv {
                            for g in &batch {
                                play_game(g, &mut map, &mut c);
                            }
                        }
                        (map, c)
                    })
                })
                .collect();
            let mut batch = Vec::with_capacity(2048);
            while read < budget {
                match reader.read_game(&mut collect) {
                    Ok(Some(g)) => {
                        batch.push(g);
                        read += 1;
                        if batch.len() == 2048 {
                            send.send(std::mem::replace(&mut batch, Vec::with_capacity(2048))).unwrap();
                        }
                    }
                    Ok(None) => break,
                    Err(e) => panic!("read error: {e}"),
                }
            }
            if !batch.is_empty() {
                send.send(batch).unwrap();
            }
            drop(send);
            hs.into_iter().map(|h| h.join().unwrap()).collect()
        });
        let parse_s = tc.elapsed().as_secs_f64();
        let mut counts = Counts::default();
        let mut runs = Vec::new();
        let mut entries = 0u64;
        // Sort and write each worker's map in parallel, then merge them into one run.
        let written: Vec<io::Result<(PathBuf, u64)>> = std::thread::scope(|s| {
            let hs: Vec<_> = results
                .into_iter()
                .enumerate()
                .map(|(i, (map, c))| {
                    counts.add(&c);
                    let p = dir.join(format!("w{i:02}.bin"));
                    s.spawn(move || write_sorted(map, &p).map(|n| (p, n)))
                })
                .collect();
            hs.into_iter().map(|h| h.join().unwrap()).collect()
        });
        for w in written {
            let (p, n) = w?;
            entries += n;
            runs.push(p);
        }
        let run = dir.join("run.bin");
        let merged = merge_files(&runs, &run)?;
        for p in &runs {
            fs::remove_file(p)?;
        }
        fs::write(dir.join("counts.txt"), counts.to_text())?;
        fs::write(&done, format!("{read}\n"))?;
        seen += read;
        let rss = peak_rss_mb();
        eprintln!(
            "chunk {chunk}: {read} games, {} obs, {entries} worker entries -> {merged} records; parse {parse_s:.1}s, total {:.1}s; elapsed {:.0}s; peak rss {rss} MB",
            counts.observations,
            tc.elapsed().as_secs_f64(),
            t0.elapsed().as_secs_f64()
        );
        if read < budget {
            break;
        }
        chunk += 1;
    }
    eprintln!("scan finished: {seen} games in {:.1}s; peak rss {} MB", t0.elapsed().as_secs_f64(), peak_rss_mb());
    Ok(())
}

fn peak_rss_mb() -> u64 {
    // getrusage ru_maxrss: bytes on macOS.
    unsafe {
        let mut ru: libc_rusage = std::mem::zeroed();
        getrusage(0, &mut ru);
        (ru.ru_maxrss as u64) / (1 << 20)
    }
}
#[repr(C)]
struct libc_rusage {
    ru_utime: [i64; 2],
    ru_stime: [i64; 2],
    ru_maxrss: i64,
    _rest: [i64; 13],
}
unsafe extern "C" {
    fn getrusage(who: i32, usage: *mut libc_rusage) -> i32;
}

// ── merge ────────────────────────────────────────────────────────────────────

struct Head {
    rec: Rec,
    src: usize,
}
impl PartialEq for Head {
    fn eq(&self, o: &Self) -> bool {
        self.rec.sort_key() == o.rec.sort_key()
    }
}
impl Eq for Head {}
impl PartialOrd for Head {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Head {
    fn cmp(&self, o: &Self) -> Ordering {
        o.rec.sort_key().cmp(&self.rec.sort_key()) // min-heap
    }
}

fn merge_files(inputs: &[PathBuf], out: &Path) -> io::Result<u64> {
    let mut readers: Vec<BufReader<File>> =
        inputs.iter().map(|p| File::open(p).map(|f| BufReader::with_capacity(1 << 20, f))).collect::<io::Result<_>>()?;
    let mut heap = BinaryHeap::new();
    for (i, r) in readers.iter_mut().enumerate() {
        if let Some(rec) = Rec::read(r)? {
            heap.push(Head { rec, src: i });
        }
    }
    let tmp = out.with_extension("tmp");
    let mut w = BufWriter::with_capacity(1 << 20, File::create(&tmp)?);
    let mut cur: Option<Rec> = None;
    let mut n = 0u64;
    while let Some(Head { rec, src }) = heap.pop() {
        if let Some(next) = Rec::read(&mut readers[src])? {
            heap.push(Head { rec: next, src });
        }
        match &mut cur {
            Some(c) if c.sort_key() == rec.sort_key() => c.absorb(&rec),
            _ => {
                if let Some(c) = cur.take() {
                    c.write(&mut w)?;
                    n += 1;
                }
                cur = Some(rec);
            }
        }
    }
    if let Some(c) = cur {
        c.write(&mut w)?;
        n += 1;
    }
    w.flush()?;
    drop(w);
    fs::rename(&tmp, out)?;
    Ok(n)
}

fn merge(args: &[String]) -> io::Result<()> {
    let out = PathBuf::from(arg(args, "--out").expect("--out FILE"));
    let inputs: Vec<PathBuf> = args.iter().skip(1).filter(|a| a.ends_with(".bin") && **a != *out.to_string_lossy()).map(PathBuf::from).collect();
    let t0 = Instant::now();
    let n = merge_files(&inputs, &out)?;
    eprintln!("merged {} runs -> {n} records ({} bytes) in {:.1}s; peak rss {} MB", inputs.len(), n * REC as u64, t0.elapsed().as_secs_f64(), peak_rss_mb());
    Ok(())
}

// ── stats ────────────────────────────────────────────────────────────────────

/// Streams the index, one position (run of equal keys) at a time.
fn for_each_position(path: &Path, mut f: impl FnMut(&[Rec])) -> io::Result<()> {
    let mut r = BufReader::with_capacity(1 << 22, File::open(path)?);
    let mut group: Vec<Rec> = Vec::new();
    while let Some(rec) = Rec::read(&mut r)? {
        if let Some(first) = group.first() {
            if first.key != rec.key {
                f(&group);
                group.clear();
            }
        }
        group.push(rec);
    }
    if !group.is_empty() {
        f(&group);
    }
    Ok(())
}

const THRESHOLDS: [u32; 4] = [3, 10, 50, 200];

fn stats(args: &[String]) -> io::Result<()> {
    let index = PathBuf::from(arg(args, "--index").expect("--index FILE"));
    let cap = 64usize;
    // [ply] distinct positions; [ply][t] positions with total games >= T;
    // [band][ply][t] positions whose games by movers in that band >= T;
    // owner band (1..=3, 600–1199) as its own row.
    let mut distinct = vec![0u64; cap];
    let mut clear = vec![[0u64; 4]; cap];
    let mut clear_band = vec![vec![[0u64; 4]; cap]; BANDS + 1];
    let mut records = 0u64;
    let mut pos_moves = 0u64; // distinct (position, move)
    let mut pos_move_band = 0u64; // distinct (position, move, band)
    let mut pos_move_speed = 0u64; // distinct (position, move, speed)
    let mut positions = 0u64;
    let mut obs = 0u64;
    let t0 = Instant::now();
    for_each_position(&index, |g| {
        positions += 1;
        records += g.len() as u64;
        let ply = g.iter().map(|r| r.minply).min().unwrap() as usize;
        let ply = ply.min(cap - 1);
        distinct[ply] += 1;
        let mut by_band = [0u64; 16];
        let mut total = 0u64;
        let mut i = 0;
        while i < g.len() {
            let mv = g[i].mv;
            let (mut bands, mut speeds) = (0u16, 0u8);
            while i < g.len() && g[i].mv == mv {
                let r = &g[i];
                by_band[(r.dims >> 3) as usize] += r.n as u64;
                total += r.n as u64;
                bands |= 1 << (r.dims >> 3);
                speeds |= 1 << (r.dims & 7);
                i += 1;
            }
            pos_moves += 1;
            pos_move_band += bands.count_ones() as u64;
            pos_move_speed += speeds.count_ones() as u64;
        }
        obs += total;
        let owner = by_band[1] + by_band[2] + by_band[3];
        for (t, &th) in THRESHOLDS.iter().enumerate() {
            if total >= th as u64 {
                clear[ply][t] += 1;
            }
            for b in 0..BANDS {
                if by_band[b] >= th as u64 {
                    clear_band[b][ply][t] += 1;
                }
            }
            if owner >= th as u64 {
                clear_band[BANDS][ply][t] += 1;
            }
        }
    })?;
    println!("index {} : {} records, {} bytes; read in {:.1}s", index.display(), records, records * REC as u64, t0.elapsed().as_secs_f64());
    println!("observations {obs}  positions {positions}  (position,move) {pos_moves}  (position,move,band) {pos_move_band}  (position,move,speed) {pos_move_speed}  (position,move,band,speed) {records}");
    println!("\nply\tdistinct\t>=3\t>=10\t>=50\t>=200");
    for p in 0..cap {
        if distinct[p] > 0 {
            println!("{p}\t{}\t{}\t{}\t{}\t{}", distinct[p], clear[p][0], clear[p][1], clear[p][2], clear[p][3]);
        }
    }
    for b in 0..=BANDS {
        let name = if b == BANDS { "owner 600-1199".to_string() } else if b == 0 { "<600".to_string() } else if b == 11 { "2600+".to_string() } else { format!("{}-{}", 400 + 200 * b, 599 + 200 * b) };
        println!("\nband {name}: positions clearing T on games by movers in the band\nply\t>=3\t>=10\t>=50\t>=200");
        for p in 0..cap {
            if distinct[p] > 0 {
                let c = clear_band[b][p];
                println!("{p}\t{}\t{}\t{}\t{}", c[0], c[1], c[2], c[3]);
            }
        }
    }
    Ok(())
}

// ── book ─────────────────────────────────────────────────────────────────────

fn parse_set(s: Option<&str>, all: usize) -> Vec<bool> {
    let mut v = vec![s.is_none(); 16];
    if let Some(s) = s {
        for part in s.split(',') {
            if let Some((a, b)) = part.split_once('-') {
                for i in a.parse::<usize>().unwrap()..=b.parse::<usize>().unwrap() {
                    v[i] = true;
                }
            } else {
                v[part.parse::<usize>().unwrap()] = true;
            }
        }
    }
    v.truncate(16.max(all));
    v
}

/// A Polyglot book in the current book's weight formula (win 2, draw 1, for the side
/// to move; Polyglot's halving when a position's weights pass 16 bits; zero-weight
/// moves dropped, as python-chess's reader ignores them). For measuring stage 0 only:
/// the formula the generated books will use is a stage-2 decision.
fn book(args: &[String]) -> io::Result<()> {
    let index = PathBuf::from(arg(args, "--index").expect("--index FILE"));
    let out = PathBuf::from(arg(args, "--out").expect("--out FILE"));
    let min_games: u64 = arg(args, "--min-games").map(|s| s.parse().unwrap()).unwrap_or(3);
    let bands = parse_set(arg(args, "--bands"), 16);
    let speeds = parse_set(arg(args, "--speeds"), 6);
    let mut entries: Vec<(u64, u16, u16)> = Vec::new();
    for_each_position(&index, |g| {
        let white_to_move = g.iter().map(|r| r.minply).min().unwrap() % 2 == 0;
        let mut moves: Vec<(u16, u64)> = Vec::new();
        let mut i = 0;
        while i < g.len() {
            let mv = g[i].mv;
            let (mut n, mut w, mut d) = (0u64, 0u64, 0u64);
            while i < g.len() && g[i].mv == mv {
                let r = &g[i];
                if bands[(r.dims >> 3) as usize] && speeds[(r.dims & 7) as usize] {
                    n += r.n as u64;
                    w += r.w as u64;
                    d += r.d as u64;
                }
                i += 1;
            }
            if n >= min_games {
                let wins = if white_to_move { w } else { n - w - d };
                moves.push((mv, 2 * wins + d));
            }
        }
        let mut max = moves.iter().map(|m| m.1).max().unwrap_or(0);
        while max > 0xFFFF {
            for m in moves.iter_mut() {
                m.1 /= 2;
            }
            max /= 2;
        }
        for (mv, wt) in moves {
            if wt > 0 {
                entries.push((g[0].key, mv, wt as u16));
            }
        }
    })?;
    entries.sort_unstable_by_key(|e| (e.0, std::cmp::Reverse(e.2)));
    let mut w = BufWriter::new(File::create(&out)?);
    for (k, mv, wt) in &entries {
        w.write_all(&k.to_be_bytes())?;
        w.write_all(&mv.to_be_bytes())?;
        w.write_all(&wt.to_be_bytes())?;
        w.write_all(&0u32.to_be_bytes())?;
    }
    w.flush()?;
    eprintln!("book {}: {} entries", out.display(), entries.len());
    Ok(())
}

// ── hashes (verification) ────────────────────────────────────────────────────

fn hashes(args: &[String]) -> io::Result<()> {
    let n: usize = arg(args, "--games").map(|s| s.parse().unwrap()).unwrap_or(1000);
    let mut reader = Reader::new(BufReader::new(io::stdin().lock()));
    let mut collect = Collect { cap: 400, want_evals: false };
    let mut out = BufWriter::new(io::stdout().lock());
    for _ in 0..n {
        let Some(g) = reader.read_game(&mut collect)? else { break };
        let mut pos = Chess::default();
        for san in &g.sans {
            let Ok(m) = san.to_move(&pos) else { break };
            let fen = Fen::from_position(&pos, EnPassantMode::Always);
            writeln!(out, "{fen}\t{:016x}\t{}", key_of(&pos), polyglot_move(&m))?;
            pos.play_unchecked(m);
        }
    }
    Ok(())
}

// ── targets / evals: the engine layer's position set and its [%eval] coverage ─

/// Positions whose games by movers in `--bands` reach `--min-games`, at plies up to
/// `--max-ply`, with their `--top` most-played moves in those bands. One line each:
/// key, shallowest ply, games, then move:games pairs.
fn targets(args: &[String]) -> io::Result<()> {
    let index = PathBuf::from(arg(args, "--index").expect("--index FILE"));
    let out = PathBuf::from(arg(args, "--out").expect("--out FILE"));
    let min_games: u64 = arg(args, "--min-games").map(|s| s.parse().unwrap()).unwrap_or(50);
    let max_ply: u8 = arg(args, "--max-ply").map(|s| s.parse().unwrap()).unwrap_or(20);
    let top: usize = arg(args, "--top").map(|s| s.parse().unwrap()).unwrap_or(3);
    let bands = parse_set(arg(args, "--bands"), 16);
    let mut w = BufWriter::new(File::create(&out)?);
    let mut n = 0u64;
    for_each_position(&index, |g| {
        let minply = g.iter().map(|r| r.minply).min().unwrap();
        if minply > max_ply {
            return;
        }
        let mut moves: Vec<(u16, u64)> = Vec::new();
        for r in g {
            if !bands[(r.dims >> 3) as usize] {
                continue;
            }
            match moves.last_mut() {
                Some(m) if m.0 == r.mv => m.1 += r.n as u64,
                _ => moves.push((r.mv, r.n as u64)),
            }
        }
        let total: u64 = moves.iter().map(|m| m.1).sum();
        if total < min_games {
            return;
        }
        moves.sort_by_key(|m| std::cmp::Reverse(m.1));
        let tops: Vec<String> = moves.iter().take(top).map(|(mv, c)| format!("{mv}:{c}")).collect();
        writeln!(w, "{:016x}\t{minply}\t{total}\t{}", g[0].key, tops.join(",")).unwrap();
        n += 1;
    })?;
    w.flush()?;
    eprintln!("targets {}: {n} positions", out.display());
    Ok(())
}

/// Up to this many evals are kept per position or move; the median of them is reported.
/// Positions seen in many games carry many evals, sometimes from different Stockfish
/// versions, so one value would be a sample of one.
const KEEP_EVALS: usize = 31;

#[derive(Clone, Default)]
struct Cover {
    fen: Option<String>,
    own: (u32, Vec<i32>),             // evals seen of the position itself; kept values
    child: Vec<(u16, u32, Vec<i32>)>, // per top move: evals seen after it; kept values
    /// Opening families of every game reaching the position (Lichess `Opening` header).
    families: FxHashMap<String, u32>,
}

fn keep(v: &mut Vec<i32>, e: i32) {
    if v.len() < KEEP_EVALS {
        v.push(e);
    }
}

fn median(v: &[i32]) -> i32 {
    if v.is_empty() {
        return NO_EVAL;
    }
    let mut s = v.to_vec();
    s.sort_unstable();
    s[s.len() / 2]
}

/// Re-scans PGN (stdin) for the target positions: whether a Lichess `[%eval]` exists for
/// each target and for the position after each of its top moves, and the target's FEN.
fn evals(args: &[String]) -> io::Result<()> {
    let tpath = PathBuf::from(arg(args, "--targets").expect("--targets FILE"));
    let out = PathBuf::from(arg(args, "--out").expect("--out FILE"));
    let workers: usize = arg(args, "--workers").map(|s| s.parse().unwrap()).unwrap_or(8);
    let max_ply: usize = arg(args, "--max-ply").map(|s| s.parse().unwrap()).unwrap_or(20);
    let max_games: u64 = arg(args, "--max-games").map(|s| s.parse().unwrap()).unwrap_or(u64::MAX);
    let mut lines: Vec<String> = Vec::new();
    let mut index: FxHashMap<u64, usize> = FxHashMap::default();
    let mut base: Vec<Cover> = Vec::new();
    for line in fs::read_to_string(&tpath)?.lines() {
        let f: Vec<&str> = line.split('\t').collect();
        let key = u64::from_str_radix(f[0], 16).unwrap();
        index.insert(key, base.len());
        let child = f[3]
            .split(',')
            .filter(|x| !x.is_empty())
            .map(|x| (x.split(':').next().unwrap().parse().unwrap(), 0, Vec::new()))
            .collect();
        base.push(Cover { fen: None, own: (0, Vec::new()), child, families: FxHashMap::default() });
        lines.push(line.to_string());
    }
    let t0 = Instant::now();
    let stdin = io::stdin().lock();
    let mut reader = Reader::new(BufReader::with_capacity(1 << 22, stdin));
    // Two past the last ply used: the eval after ply `max_ply` sits in the comment that
    // follows it, and the reader stops reading a game as soon as the cap is reached.
    let mut collect = Collect { cap: max_ply + 2, want_evals: true };
    let (send, recv) = crossbeam_channel::bounded::<Vec<Game>>(64);
    let index = &index;
    let base_ref = &base;
    let (games, with_evals, merged) = std::thread::scope(|s| {
        let hs: Vec<_> = (0..workers)
            .map(|_| {
                let recv = recv.clone();
                s.spawn(move || {
                    let mut cov: FxHashMap<usize, Cover> = FxHashMap::default();
                    let mut with_evals = 0u64;
                    for batch in recv {
                        for g in &batch {
                            if g.result == 3 {
                                continue;
                            }
                            // Every game votes on its positions' families; only games with
                            // evals contribute evals.
                            let has_evals = g.evals.iter().any(|&e| e != NO_EVAL);
                            with_evals += has_evals as u64;
                            let mut pos = Chess::default();
                            for (ply, san) in g.sans.iter().enumerate().take(max_ply + 1) {
                                let Ok(m) = san.to_move(&pos) else { break };
                                if let Some(&t) = index.get(&key_of(&pos)) {
                                    let c = cov.entry(t).or_insert_with(|| base_ref[t].clone());
                                    if c.fen.is_none() {
                                        c.fen = Some(Fen::from_position(&pos, EnPassantMode::Legal).to_string());
                                    }
                                    if !g.family.is_empty() {
                                        *c.families.entry(g.family.clone()).or_insert(0) += 1;
                                    }
                                    if !has_evals {
                                        pos.play_unchecked(m);
                                        continue;
                                    }
                                    if ply > 0 && g.evals[ply - 1] != NO_EVAL {
                                        keep(&mut c.own.1, g.evals[ply - 1]);
                                        c.own.0 += 1;
                                    }
                                    let mv = polyglot_move(&m);
                                    if let Some(ch) = c.child.iter_mut().find(|x| x.0 == mv) {
                                        if g.evals[ply] != NO_EVAL {
                                            keep(&mut ch.2, g.evals[ply]);
                                            ch.1 += 1;
                                        }
                                    }
                                }
                                pos.play_unchecked(m);
                            }
                        }
                    }
                    (cov, with_evals)
                })
            })
            .collect();
        let mut batch = Vec::with_capacity(2048);
        let mut games = 0u64;
        while games < max_games {
            match reader.read_game(&mut collect) {
                Ok(Some(g)) => {
                    batch.push(g);
                    games += 1;
                    if batch.len() == 2048 {
                        send.send(std::mem::replace(&mut batch, Vec::with_capacity(2048))).unwrap();
                    }
                }
                Ok(None) => break,
                Err(e) => panic!("read error: {e}"),
            }
        }
        if !batch.is_empty() {
            send.send(batch).unwrap();
        }
        drop(send);
        let mut merged: Vec<Cover> = base_ref.clone();
        let mut with_evals = 0u64;
        for h in hs {
            let (cov, we) = h.join().unwrap();
            with_evals += we;
            for (t, c) in cov {
                let m = &mut merged[t];
                if m.fen.is_none() {
                    m.fen = c.fen;
                }
                for (f, k) in c.families {
                    *m.families.entry(f).or_insert(0) += k;
                }
                m.own.0 += c.own.0;
                for e in c.own.1 {
                    keep(&mut m.own.1, e);
                }
                for (a, b) in m.child.iter_mut().zip(c.child) {
                    a.1 += b.1;
                    for e in b.2 {
                        keep(&mut a.2, e);
                    }
                }
            }
        }
        (games, with_evals, merged)
    });
    let mut w = BufWriter::new(File::create(&out)?);
    for (line, c) in lines.iter().zip(&merged) {
        // Same columns as before; the value is now the median of the kept evals.
        let ch: Vec<String> = c.child.iter().map(|(mv, n, e)| format!("{mv}:{n}:{}", median(e))).collect();
        let total: u32 = c.families.values().sum();
        let top = c.families.iter().max_by_key(|(f, k)| (**k, std::cmp::Reverse((*f).clone())));
        let fam = top.map(|(f, k)| format!("{f}|{k}|{total}")).unwrap_or_else(|| "-".into());
        writeln!(w, "{line}\t{}\t{}:{}\t{}\t{fam}", c.fen.as_deref().unwrap_or("-"), c.own.0, median(&c.own.1), ch.join(","))?;
    }
    w.flush()?;
    eprintln!(
        "evals: {games} games read, {with_evals} with [%eval], {:.1}s; peak rss {} MB",
        t0.elapsed().as_secs_f64(),
        peak_rss_mb()
    );
    Ok(())
}

/// Re-scans PGN (stdin) for the FEN of every target key, for the engine layer: one line
/// per target found, `key<TAB>FEN`, in no particular order. Stops reading as soon as every
/// target has been seen. Lighter than `evals`: no families, no eval tags, so it scales to
/// millions of targets.
fn fens(args: &[String]) -> io::Result<()> {
    use std::sync::atomic::{AtomicBool, AtomicU64, Ordering as AO};
    let tpath = PathBuf::from(arg(args, "--targets").expect("--targets FILE"));
    let out = PathBuf::from(arg(args, "--out").expect("--out FILE"));
    let workers: usize = arg(args, "--workers").map(|s| s.parse().unwrap()).unwrap_or(8);
    let max_ply: usize = arg(args, "--max-ply").map(|s| s.parse().unwrap()).unwrap_or(24);
    let mut index: FxHashMap<u64, usize> = FxHashMap::default();
    for line in fs::read_to_string(&tpath)?.lines() {
        let key = u64::from_str_radix(line.split('\t').next().unwrap(), 16).unwrap();
        let n = index.len();
        index.entry(key).or_insert(n);
    }
    let seen: Vec<AtomicBool> = (0..index.len()).map(|_| AtomicBool::new(false)).collect();
    let found = AtomicU64::new(0);
    let total = index.len() as u64;
    let t0 = Instant::now();
    let mut reader = Reader::new(BufReader::with_capacity(1 << 22, io::stdin().lock()));
    let mut collect = Collect { cap: max_ply + 1, want_evals: false };
    let (send, recv) = crossbeam_channel::bounded::<Vec<Game>>(64);
    let (index, seen, found) = (&index, &seen, &found);
    let games = std::thread::scope(|s| {
        let hs: Vec<_> = (0..workers)
            .map(|_| {
                let recv = recv.clone();
                s.spawn(move || {
                    let mut got: Vec<(u64, String)> = Vec::new();
                    for batch in recv {
                        for g in &batch {
                            let mut pos = Chess::default();
                            for san in g.sans.iter().take(max_ply + 1) {
                                let key = key_of(&pos);
                                if let Some(&t) = index.get(&key) {
                                    if !seen[t].load(AO::Relaxed) && !seen[t].swap(true, AO::Relaxed) {
                                        got.push((key, Fen::from_position(&pos, EnPassantMode::Legal).to_string()));
                                        found.fetch_add(1, AO::Relaxed);
                                    }
                                }
                                let Ok(m) = san.to_move(&pos) else { break };
                                pos.play_unchecked(m);
                            }
                        }
                    }
                    got
                })
            })
            .collect();
        let mut batch = Vec::with_capacity(2048);
        let mut games = 0u64;
        loop {
            match reader.read_game(&mut collect) {
                Ok(Some(g)) => {
                    batch.push(g);
                    games += 1;
                    if batch.len() == 2048 {
                        send.send(std::mem::replace(&mut batch, Vec::with_capacity(2048))).unwrap();
                        if found.load(AO::Relaxed) == total {
                            break;
                        }
                    }
                }
                Ok(None) => break,
                Err(e) => panic!("read error: {e}"),
            }
        }
        if !batch.is_empty() {
            send.send(batch).unwrap();
        }
        drop(send);
        let mut w = BufWriter::new(File::create(&out).unwrap());
        for h in hs {
            for (key, fen) in h.join().unwrap() {
                writeln!(w, "{key:016x}\t{fen}").unwrap();
            }
        }
        w.flush().unwrap();
        games
    });
    eprintln!(
        "fens: {} of {total} targets found in {games} games, {:.1}s; peak rss {} MB",
        found.load(AO::Relaxed),
        t0.elapsed().as_secs_f64(),
        peak_rss_mb()
    );
    Ok(())
}

/// Sums the per-chunk counters of a scan directory.
fn counts(args: &[String]) -> io::Result<()> {
    let dir = PathBuf::from(args.get(1).expect("counts DIR"));
    let mut total = Counts::default();
    let mut chunks = 0;
    let mut names: Vec<_> = fs::read_dir(&dir)?.filter_map(|e| e.ok()).map(|e| e.path()).collect();
    names.sort();
    for p in names {
        if p.join("DONE").exists() {
            total.add(&Counts::from_text(&fs::read_to_string(p.join("counts.txt"))?));
            chunks += 1;
        }
    }
    print!("chunks {chunks}\n{}", total.to_text());
    Ok(())
}

fn main() -> io::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(|s| s.as_str()) {
        Some("scan") => scan(&args),
        Some("merge") => merge(&args),
        Some("stats") => stats(&args),
        Some("book") => book(&args),
        Some("hashes") => hashes(&args),
        Some("counts") => counts(&args),
        Some("targets") => targets(&args),
        Some("evals") => evals(&args),
        Some("fens") => fens(&args),
        _ => {
            eprintln!("usage: opening-index scan|merge|stats|book|hashes …");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn polyglot_reference_keys() {
        // Reference values from the Polyglot book format specification.
        for (fen, key) in [
            ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 0x463b96181691fc9c_u64),
            ("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1", 0x823c9b50fd114196),
            ("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3", 0x22a48b5a8e47ff78),
            ("rnbqkbnr/p1pppppp/8/8/PpP4P/8/1P1PPPP1/RNBQKBNR b KQkq c3 0 3", 0x3c8123ea7b067637),
        ] {
            let pos: Chess = fen.parse::<Fen>().unwrap().into_position(pgn_reader::shakmaty::CastlingMode::Standard).unwrap();
            assert_eq!(key_of(&pos), key, "{fen}");
        }
    }

    #[test]
    fn ep_file_hashed_even_when_the_capture_is_illegal() {
        // White has just played g2-g4; Black's f4 pawn could take e.p. but is pinned by
        // Qf3. python-chess hashes the e.p. file here (0x8ae84566b2f832ac, measured).
        let mut pos: Chess = "8/8/8/5k2/5p2/3K1Q2/5PPP/8 w - - 0 38".parse::<Fen>().unwrap()
            .into_position(pgn_reader::shakmaty::CastlingMode::Standard).unwrap();
        let m = "g4".parse::<San>().unwrap().to_move(&pos).unwrap();
        pos.play_unchecked(m);
        assert_eq!(key_of(&pos), 0x8ae84566b2f832ac);
    }

    #[test]
    fn evals_parse() {
        assert_eq!(parse_eval(b" [%eval 0.17] [%clk 0:03:00] "), Some(17));
        assert_eq!(parse_eval(b" [%eval -1.5] "), Some(-150));
        assert_eq!(parse_eval(b" [%eval #3] "), Some(99_997));
        assert_eq!(parse_eval(b" [%eval #-2] "), Some(-99_998));
        assert_eq!(parse_eval(b" [%clk 0:03:00] "), None);
    }

    #[test]
    fn bands_and_speeds() {
        assert_eq!(band_of(599), 0);
        assert_eq!(band_of(600), 1);
        assert_eq!(band_of(1199), 3);
        assert_eq!(band_of(2600), 11);
        assert_eq!(band_of(0), 15);
        assert_eq!(speed_of(b"60+0"), 1);
        assert_eq!(speed_of(b"180+0"), 2);
        assert_eq!(speed_of(b"600+0"), 3);
        assert_eq!(speed_of(b"1800+0"), 4);
        assert_eq!(speed_of(b"-"), 5);
        assert_eq!(speed_of(b"15+0"), 0);
    }
}
