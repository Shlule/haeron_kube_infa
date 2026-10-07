#!/usr/bin/env python3
"""Politique de rétention des sauvegardes Vault.

Entrée (stdin) : une clé S3 par ligne.
Sortie (stdout) : les clés à SUPPRIMER, une par ligne.

Règles :
  - fenêtre quotidienne : les 7 derniers jours (âge < 7 j) -> on garde la plus récente de chaque jour
  - au-delà : on garde une sauvegarde par tranche de 14 jours (la plus ancienne de la tranche,
    ce qui rend le choix stable d'un jour à l'autre)
  - tout le reste est supprimé
  - seules les clés au format vault-YYYYMMDD-HHMMSS.snap.gpg sont considérées ; le reste n'est jamais touché
"""
import argparse
import re
import sys
from datetime import datetime, timezone, timedelta

PATTERN = re.compile(r"^vault-(\d{8})-(\d{6})\.snap\.gpg$")
DAILY_DAYS = 7
BUCKET_DAYS = 14


def parse(key):
    m = PATTERN.match(key)
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def compute_deletions(keys, now, max_age_days=730):
    items = []
    for k in keys:
        ts = parse(k.strip())
        if ts:
            items.append((ts, k.strip()))
    items.sort()

    keep = set()
    daily_cut = now - timedelta(days=DAILY_DAYS)

    # quotidien : la plus récente par jour dans la fenêtre
    per_day = {}
    for ts, k in items:
        if ts > daily_cut:
            per_day[ts.date()] = k  # trié croissant -> la dernière écrase
    keep.update(per_day.values())

    # bi-hebdomadaire : la plus ancienne de chaque tranche de 14 jours, hors fenêtre quotidienne
    per_bucket = {}
    for ts, k in items:
        if ts <= daily_cut:
            per_bucket.setdefault(ts.date().toordinal() // BUCKET_DAYS, k)
    keep.update(per_bucket.values())

    # âge maximum : plus rien n'est conservé au-delà
    max_cut = now - timedelta(days=max_age_days)
    keep = {k for k in keep if parse(k) >= max_cut}

    return [k for _, k in items if k not in keep]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="YYYY-MM-DD (tests)")
    ap.add_argument("--max-age-days", type=int, default=730, help="âge maximum conservé (défaut: 2 ans)")
    args = ap.parse_args()
    if args.today:
        now = datetime.strptime(args.today, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
    keys = [l for l in sys.stdin.read().split() if l and l != "None"]
    for k in compute_deletions(keys, now, args.max_age_days):
        print(k)


if __name__ == "__main__":
    main()