"""Generate a year of realistic stock data for a fictional two-site GP practice.

The tables have the same shape as the GP Inventory app's collections
(sites, categories, items, site stock, movements, batches, requests, users),
so the same analysis would run on a real export. All names and numbers here
are made up.

How the year is simulated, day by day, for every item at every site:
  - Staff use stock. Demand depends on the weekday (closed Sundays, quiet
    Saturdays) and, for clinical items, the winter flu-clinic season.
  - Use always comes out of the earliest-expiring batch first, and expired
    stock is never used (the app enforces both).
  - When stock falls to the reorder level, someone raises a request. A
    manager approves it some hours later, and the delivery arrives a few
    days after that, as a new batch with its own expiry date.
  - People over-order slow movers, so some batches expire on the shelf and
    are disposed of; a little stock is damaged or lost.
  - On Mondays, a site that has run out can borrow from the other site.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from gpstock import DATA_DIR

START, END = date(2025, 10, 1), date(2026, 9, 30)
SEED = 7

SITES = [("S1", "Main Surgery", 1.0), ("S2", "Branch Surgery", 0.55)]
CATEGORIES = [
    ("C1", "Tea & Coffee", False), ("C2", "Milk & Dairy", False), ("C3", "Kitchen & Pantry", False),
    ("C4", "Cleaning & Hygiene", False), ("C5", "Stationery & Office", False),
    ("C6", "Medical Consumables", True), ("C7", "Medical Equipment", True), ("C8", "PPE", True),
]
# name, category, unit, unit cost £, daily use at main site, reorder level, order up to,
# shelf life days (None = no expiry), lead days, winter uplift, supplier
ITEMS = [
    ("Coffee 200g", "C1", "jar", 4.50, 0.45, 2, 8, 540, 1, 1.1, "Supermarket"),
    ("Tea bags (240)", "C1", "box", 5.00, 0.30, 2, 6, 540, 1, 1.1, "Supermarket"),
    ("Hot chocolate", "C1", "tub", 3.50, 0.08, 1, 3, 365, 1, 1.4, "Supermarket"),
    ("Semi-skimmed milk 2pt", "C2", "bottle", 1.45, 1.20, 3, 7, 10, 1, 1.0, "Supermarket"),
    ("Oat milk 1L", "C2", "carton", 1.80, 0.25, 2, 6, 120, 1, 1.0, "Supermarket"),
    ("Sugar 1kg", "C3", "pack", 1.10, 0.06, 1, 3, 720, 1, 1.0, "Supermarket"),
    ("Biscuits", "C3", "pack", 1.20, 0.35, 3, 10, 180, 1, 1.2, "Supermarket"),
    ("Kitchen roll (4)", "C3", "pack", 3.50, 0.20, 2, 6, None, 2, 1.0, "Bunzl Healthcare"),
    ("Hand sanitiser 500ml", "C4", "bottle", 3.20, 0.55, 6, 20, 730, 3, 1.5, "Bunzl Healthcare"),
    ("Hand wash 5L", "C4", "bottle", 9.00, 0.10, 2, 5, 730, 3, 1.2, "Bunzl Healthcare"),
    ("Clinical wipes (200)", "C4", "tub", 6.50, 0.80, 8, 24, 540, 3, 1.4, "Bunzl Healthcare"),
    ("Bin bags (50)", "C4", "roll", 4.00, 0.25, 3, 8, None, 3, 1.0, "Bunzl Healthcare"),
    ("Toilet roll (36)", "C4", "case", 18.00, 0.12, 2, 5, None, 3, 1.1, "Bunzl Healthcare"),
    ("Paper towels", "C4", "case", 22.00, 0.10, 2, 5, None, 3, 1.2, "Bunzl Healthcare"),
    ("A4 printer paper", "C5", "box", 22.00, 0.18, 2, 6, None, 2, 1.0, "Office supplier"),
    ("Printer toner", "C5", "cartridge", 65.00, 0.04, 1, 3, None, 3, 1.0, "Office supplier"),
    ("Envelopes C5 (500)", "C5", "box", 12.00, 0.03, 1, 3, None, 2, 1.0, "Office supplier"),
    ("Specimen labels", "C5", "roll", 8.00, 0.09, 2, 6, None, 3, 1.2, "Office supplier"),
    ("Prescription bags", "C5", "pack", 15.00, 0.05, 1, 3, None, 2, 1.0, "Office supplier"),
    ("Nitrile gloves S", "C6", "box", 4.50, 0.35, 6, 20, 1095, 4, 1.3, "Medisave"),
    ("Nitrile gloves M", "C6", "box", 4.50, 0.80, 10, 30, 1095, 4, 1.3, "Medisave"),
    ("Nitrile gloves L", "C6", "box", 4.50, 0.40, 6, 20, 1095, 4, 1.3, "Medisave"),
    ("Syringes 5ml (100)", "C6", "box", 9.00, 0.12, 2, 6, 730, 4, 1.8, "Medisave"),
    ("Needles 23G (100)", "C6", "box", 6.00, 0.12, 2, 6, 730, 4, 1.8, "Medisave"),
    ("Sterile dressings 10x10", "C6", "pack", 7.00, 0.30, 4, 12, 365, 4, 1.1, "Medisave"),
    ("Alcohol swabs (200)", "C6", "box", 3.50, 0.20, 3, 10, 540, 4, 1.6, "Medisave"),
    ("Specimen pots (100)", "C6", "box", 12.00, 0.10, 2, 6, 365, 4, 1.1, "Medisave"),
    ("Urine dipsticks (100)", "C6", "tub", 18.00, 0.04, 1, 4, 150, 5, 1.0, "Medisave"),
    ("EDTA blood bottles (100)", "C6", "box", 16.00, 0.07, 2, 6, 240, 5, 1.1, "Medisave"),
    ("Sharps bin 5L", "C6", "pcs", 4.00, 0.10, 3, 10, None, 4, 1.3, "Medisave"),
    ("Tongue depressors (100)", "C6", "box", 3.00, 0.03, 1, 4, 1095, 4, 1.3, "Medisave"),
    ("Thermometer probe covers", "C7", "box", 11.00, 0.10, 2, 6, 730, 5, 1.5, "Medisave"),
    ("BP cuff (adult)", "C7", "pcs", 18.00, 0.01, 1, 2, None, 5, 1.0, "Medisave"),
    ("Pulse oximeter", "C7", "pcs", 30.00, 0.008, 1, 2, None, 5, 1.0, "Medisave"),
    ("Otoscope specula (250)", "C7", "box", 12.00, 0.04, 1, 3, None, 5, 1.4, "Medisave"),
    ("Type IIR face masks (50)", "C8", "box", 6.00, 0.30, 4, 14, 365, 4, 2.0, "Bunzl Healthcare"),
    ("Aprons (200)", "C8", "roll", 8.00, 0.12, 2, 6, 1095, 4, 1.3, "Bunzl Healthcare"),
    ("Face shields (10)", "C8", "box", 10.00, 0.02, 1, 4, 365, 4, 1.5, "Bunzl Healthcare"),
    ("FFP3 masks (20)", "C8", "box", 60.00, 0.01, 1, 3, 300, 5, 2.0, "Bunzl Healthcare"),
]
STAFF = [("U1", "Practice Manager", "manager"), ("U2", "Assistant Manager", "manager"),
         ("U3", "Practice Nurse A", "nurse"), ("U4", "Practice Nurse B", "nurse"), ("U5", "HCA", "nurse"),
         ("U6", "Receptionist A", "admin"), ("U7", "Receptionist B", "admin"), ("U8", "Admin Coordinator", "admin")]
WEEKDAY = [1.0, 1.05, 1.0, 1.0, 0.95, 0.25, 0.0]       # Mon..Sun


@dataclass
class Batch:
    batch_id: str
    number: str
    expiry: date | None
    qty: int
    received: date


@dataclass
class Shelf:
    batches: list = field(default_factory=list)
    open_request: str | None = None
    retry_after: date | None = None

    @property
    def qty(self):
        return sum(b.qty for b in self.batches)

    def usable(self, day):
        return sum(b.qty for b in self.batches if b.expiry is None or b.expiry >= day)


class Sim:
    def __init__(self):
        self.rng = np.random.default_rng(SEED)
        self.items = [dict(item_id=f"I{i + 1:02d}", name=n, category_id=c, unit=u, unit_cost=cost, rate=r,
                           reorder=ro, order_to=ot, shelf_life=sl, lead=ld, winter=w, supplier=sup,
                           tracked=dict((k, t) for k, _, t in CATEGORIES)[c])
                      for i, (n, c, u, cost, r, ro, ot, sl, ld, w, sup) in enumerate(ITEMS)]
        self.shelves = {(s, it["item_id"]): Shelf() for s, _, _ in SITES for it in self.items}
        self.movements, self.batches, self.requests, self.deliveries, self.unmet = [], [], [], [], []
        self.seq = {"M": 0, "B": 0, "R": 0}
        # Some items are over-ordered by habit (bigger orders, so more of them expire).
        self.over_order = {it["item_id"]: self.rng.choice([1.0, 1.0, 1.0, 1.3, 1.7]) for it in self.items}

    def nid(self, kind):
        self.seq[kind] += 1
        return f"{kind}{self.seq[kind]:06d}"

    def when(self, day, h0=8, h1=18):
        return datetime.combine(day, datetime.min.time()) + timedelta(minutes=int(self.rng.integers(h0 * 60, h1 * 60)))

    def staff(self, role=None):
        pool = [u for u in STAFF if role is None or u[2] == role]
        return pool[self.rng.integers(len(pool))][0]

    def season(self, item, day):
        # Flu clinics and winter pressure run October to February.
        return item["winter"] if day.month in (10, 11, 12, 1, 2) else 1.0

    def cost(self, item, day):
        drift = 1 + 0.06 * (day - START).days / 365          # prices creep up through the year
        return round(item["unit_cost"] * drift * self.rng.uniform(0.95, 1.05), 2)

    def move(self, day, site, item, kind, qty, reason="", source="", unit_cost=None, user=None, batch=None,
             request=None, transfer_site=None, at=None):
        self.movements.append({
            "movement_id": self.nid("M"), "item_id": item["item_id"], "site_id": site, "transfer_site_id": transfer_site,
            "type": kind, "quantity": qty, "balance_after": self.shelves[(site, item["item_id"])].qty,
            "reason": reason, "source": source, "unit_cost": unit_cost, "batch_id": batch, "request_id": request,
            "user_id": user or self.staff(), "date": at or self.when(day)})

    def receive(self, day, site, item, qty, source, unit_cost, request=None, expiry=None, number=None, user=None):
        if item["tracked"] or item["shelf_life"]:
            if expiry is None and item["shelf_life"]:
                # Deliveries arrive part-way through their shelf life; fresh food arrives fresh.
                low = 0.8 if item["shelf_life"] < 30 else 0.35
                expiry = day + timedelta(days=int(item["shelf_life"] * self.rng.uniform(low, 1.0)))
            number = number or f"{item['name'][:2].upper()}-{int(self.rng.integers(1000, 9999))}"
        b = Batch(self.nid("B"), number or "", expiry, qty, day)
        self.shelves[(site, item["item_id"])].batches.append(b)
        self.batches.append({"batch_id": b.batch_id, "item_id": item["item_id"], "site_id": site,
                             "batch_number": b.number, "expiry_date": expiry, "received_quantity": qty,
                             "received_at": day, "source": source, "_obj": b})
        self.move(day, site, item, "in", qty, source=source, unit_cost=unit_cost, batch=b.batch_id,
                  request=request, user=user or self.staff("manager"))

    def take(self, day, site, item, qty, reason, user=None, include_expired=False):
        """Take stock out, earliest expiry first. Returns what was actually taken."""
        shelf = self.shelves[(site, item["item_id"])]
        taken = 0
        for b in sorted(shelf.batches, key=lambda b: (b.expiry or date.max, b.received)):
            if taken == qty:
                break
            if not include_expired and b.expiry is not None and b.expiry < day:
                continue
            n = min(b.qty, qty - taken)
            b.qty -= n
            taken += n
        shelf.batches = [b for b in shelf.batches if b.qty > 0]
        if taken:
            self.move(day, site, item, "out", taken, reason=reason, user=user)
        return taken

    def run(self):
        # Opening stock on day one.
        for s, _, factor in SITES:
            for it in self.items:
                qty = max(1, int(round(it["order_to"] * (0.6 if s == "S1" else 0.6 * factor + 0.4) * self.rng.uniform(0.6, 1.0))))
                self.receive(START, s, it, qty, "Opening stock", self.cost(it, START))
        day = START
        while day <= END:
            self.step(day)
            day += timedelta(days=1)

    def step(self, day):
        # Deliveries due today.
        for d in [d for d in self.deliveries if d["due"] == day]:
            self.receive(day, d["site"], d["item"], d["qty"], d["item"]["supplier"], self.cost(d["item"], day),
                         request=d["request_id"])
            req = next(r for r in self.requests if r["request_id"] == d["request_id"])
            req.update(status="fulfilled", fulfilled_at=self.when(day, 9, 13), fulfilled_by=self.staff("manager"))
            self.shelves[(d["site"], d["item"]["item_id"])].open_request = None
        self.deliveries = [d for d in self.deliveries if d["due"] != day]

        for s, _, factor in SITES:
            for it in self.items:
                shelf = self.shelves[(s, it["item_id"])]
                # Weekly expiry check on Mondays: dispose of anything past its date.
                if day.weekday() == 0:
                    expired = sum(b.qty for b in shelf.batches if b.expiry is not None and b.expiry < day)
                    if expired:
                        self.take(day, s, it, expired, "expired", include_expired=True)
                demand = self.rng.poisson(it["rate"] * factor * WEEKDAY[day.weekday()] * self.season(it, day))
                if demand:
                    got = self.take(day, s, it, int(demand), "used",
                                    user=self.staff("nurse" if it["category_id"] in ("C6", "C7", "C8") else None))
                    if got < demand:
                        self.unmet.append({"date": day, "site_id": s, "item_id": it["item_id"], "unmet": int(demand - got)})
                if shelf.usable(day) and self.rng.random() < 0.0015:
                    self.take(day, s, it, 1, self.rng.choice(["damaged", "lost"], p=[0.7, 0.3]))
                self.maybe_reorder(day, s, it, shelf)

        if day.weekday() == 0:
            self.transfers(day)

    def maybe_reorder(self, day, s, it, shelf):
        if shelf.open_request or shelf.usable(day) > it["reorder"] or WEEKDAY[day.weekday()] == 0:
            return
        if shelf.retry_after and day < shelf.retry_after:
            return
        target = it["order_to"] * (1 if s == "S1" else 0.6)
        qty = max(1, int(round((target - shelf.usable(day)) * self.over_order[it["item_id"]])))
        rid = self.nid("R")
        raised = self.when(day, 8, 17)
        urgent = shelf.usable(day) == 0
        # Managers look at requests a few times a day; urgent ones get seen faster.
        review_hours = float(self.rng.lognormal(np.log(3 if urgent else 18), 0.6))
        reviewed = raised + timedelta(hours=review_hours)
        if reviewed.weekday() == 6:
            reviewed += timedelta(days=1)
        status = "approved" if self.rng.random() > 0.04 else "rejected"
        self.requests.append({"request_id": rid, "item_id": it["item_id"], "item_name": it["name"], "site_id": s,
                              "category_id": it["category_id"], "quantity": qty, "unit": it["unit"],
                              "priority": "urgent" if urgent else "normal", "status": status,
                              "requested_by": self.staff(), "requested_at": raised,
                              "reviewed_by": self.staff("manager"), "reviewed_at": reviewed,
                              "fulfilled_by": None, "fulfilled_at": None})
        if status == "rejected":
            shelf.retry_after = day + timedelta(days=3)
            return
        shelf.open_request = rid
        due = reviewed.date() + timedelta(days=int(it["lead"] + self.rng.integers(0, 3)))
        while WEEKDAY[due.weekday()] == 0:
            due += timedelta(days=1)
        self.deliveries.append({"due": max(due, day + timedelta(days=1)), "site": s, "item": it, "qty": qty,
                                "request_id": rid})

    def transfers(self, day):
        for it in self.items:
            a, b = self.shelves[("S1", it["item_id"])], self.shelves[("S2", it["item_id"])]
            for (src, dst, sh_src, sh_dst) in (("S1", "S2", a, b), ("S2", "S1", b, a)):
                if sh_dst.usable(day) == 0 and sh_src.usable(day) > 2 * it["reorder"]:
                    n = max(1, it["reorder"] // 2)
                    # Batches move with their numbers and expiry dates; expired stock never moves.
                    moved = []
                    for bt in sorted(sh_src.batches, key=lambda x: (x.expiry or date.max)):
                        if bt.expiry is not None and bt.expiry < day or sum(m[1] for m in moved) >= n:
                            continue
                        k = min(bt.qty, n - sum(m[1] for m in moved))
                        moved.append((bt, k))
                    total = sum(k for _, k in moved)
                    if not total:
                        continue
                    for bt, k in moved:
                        bt.qty -= k
                    sh_src.batches = [x for x in sh_src.batches if x.qty > 0]
                    user = self.staff("manager")
                    self.move(day, src, it, "out", total, reason="transfer", transfer_site=dst, user=user)
                    for bt, k in moved:
                        self.receive(day, dst, it, k, f"Transfer from {dict((s, n) for s, n, _ in SITES)[src]}",
                                     None, expiry=bt.expiry, number=bt.number, user=user)

    def write(self):
        out = DATA_DIR / "source"
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"site_id": s, "name": n, "active": True} for s, n, _ in SITES]).to_csv(out / "sites.csv", index=False)
        pd.DataFrame([{"category_id": c, "name": n, "track_batches_by_default": t} for c, n, t in CATEGORIES]
                     ).to_csv(out / "categories.csv", index=False)
        pd.DataFrame([{k: it[k] for k in ("item_id", "name", "category_id", "unit", "supplier", "tracked")}
                      | {"default_reorder_level": it["reorder"], "list_price": it["unit_cost"]} for it in self.items]
                     ).to_csv(out / "items.csv", index=False)
        pd.DataFrame([{"site_id": s, "item_id": it["item_id"], "quantity": self.shelves[(s, it["item_id"])].qty,
                       "min_quantity": it["reorder"] if s == "S1" else max(1, int(it["reorder"] * 0.6)),
                       "stocked": True} for s, _, _ in SITES for it in self.items]).to_csv(out / "site_stock.csv", index=False)
        mv = pd.DataFrame(self.movements)
        mv["date"] = pd.to_datetime(mv["date"])
        mv.sort_values("date").to_csv(out / "movements.csv", index=False)
        bt = pd.DataFrame([{k: v for k, v in b.items() if k != "_obj"} | {"quantity_now": b["_obj"].qty}
                           for b in self.batches])
        bt.to_csv(out / "batches.csv", index=False)
        pd.DataFrame(self.requests).to_csv(out / "requests.csv", index=False)
        pd.DataFrame([{"user_id": u, "job_title": t, "role": r} for u, t, r in STAFF]).to_csv(out / "users.csv", index=False)
        pd.DataFrame(self.unmet).to_csv(out / "_unmet_demand.csv", index=False)


def generate():
    sim = Sim()
    sim.run()
    sim.write()
    mv = pd.DataFrame(sim.movements)
    print(f"Generated {len(mv):,} movements, {len(sim.requests):,} requests, {len(sim.batches):,} batches "
          f"for {len(sim.items)} items at {len(SITES)} sites")


if __name__ == "__main__":
    generate()
