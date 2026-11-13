"""Fixture helper: count a hand-built run as complete (VAL-DEATH).

Readers count a run only once `completed_at` is set, and the app sets it only through
`Database.complete_analysis_run`, which refuses a run missing any ply of its game. Tests
of aggregates (Insights, game lists) build runs with synthetic or no plies on purpose —
the plies are not what they test — so they stamp completion directly with this. Tests of
completion itself must use `complete_analysis_run`.
"""


def mark_complete(db, run_id: int, summary: dict | None = None, *,
                  white_accuracy: float | None = None,
                  black_accuracy: float | None = None) -> int:
    db.update_analysis_summary(run_id, summary or {}, white_accuracy=white_accuracy,
                               black_accuracy=black_accuracy)
    db._conn.execute(
        "UPDATE analysis_runs SET completed_at = created_at WHERE id = ?", (run_id,))
    db._conn.commit()
    return run_id
